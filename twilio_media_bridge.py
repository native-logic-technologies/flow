#!/usr/bin/env python3
"""
Twilio Media Streams ↔ LiveKit Bridge
======================================

Real-time audio bridge between Twilio phone calls and LiveKit.

Audio Flow:
-----------
Phone → Twilio → Media Stream (mulaw 8kHz) → This Bridge → LiveKit (opus 48kHz)
                                                     ↑
Phone ← Twilio ← Media Stream (mulaw 8kHz) ← This Bridge ← LiveKit (opus 48kHz)

Setup:
------
1. pip install websockets livekit asyncio
2. Set environment variables (or edit below)
3. python3 twilio_media_bridge.py
4. Configure Twilio webhook to: https://cleans2s.voiceflow.cloud/twilio-voice
5. Call your Twilio number!
"""

import asyncio
import websockets
import json
import base64
import logging
import audioop  # For mu-law conversion
import numpy as np
from flask import Flask, request, Response
from threading import Thread
import livekit
from livekit import rtc
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
LIVEKIT_URL = "ws://localhost:7880"
LIVEKIT_API_KEY = "APIQp4vjmCjrWQ9"
LIVEKIT_API_SECRET = "PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l"
ROOM_NAME = "dgx-spark-room"
TWILIO_WEBHOOK_PORT = 5000
MEDIA_STREAM_PORT = 5001

# Global state
active_calls = {}  # stream_sid -> Bridge instance


class TwilioLiveKitBridge:
    """
    Bridges a single Twilio call to LiveKit
    """
    
    def __init__(self, stream_sid, call_sid, from_number):
        self.stream_sid = stream_sid
        self.call_sid = call_sid
        self.from_number = from_number
        self.twilio_ws = None
        self.livekit_room = None
        self.audio_source = None
        self.audio_track = None
        self.subscribed_track = None
        
        # Audio conversion buffers
        self.twilio_to_lk_buffer = b''
        self.lk_to_twilio_buffer = b''
        
        # Resampling states (must persist across frames)
        self.egress_resample_state = None  # 24k -> 8k (AI to Twilio)
        self.ingress_resample_state = None  # 8k -> 24k (Twilio to AI)
        
        # Statistics
        self.frames_received = 0
        self.frames_sent = 0
        self.start_time = time.time()
        
    async def connect_livekit(self):
        """Connect to LiveKit room as a participant"""
        try:
            logger.info(f"[{self.stream_sid}] Connecting to LiveKit room: {ROOM_NAME}")
            
            # Generate JWT token
            import jwt
            from datetime import datetime, timedelta
            
            now = datetime.utcnow()
            token_payload = {
                "exp": now + timedelta(hours=1),
                "iss": LIVEKIT_API_KEY,
                "sub": f"phone-{self.from_number}",
                "nbf": now,
                "video": {
                    "roomJoin": True,
                    "room": ROOM_NAME,
                    "canPublish": True,
                    "canSubscribe": True,
                    "canPublishData": True
                }
            }
            token = jwt.encode(token_payload, LIVEKIT_API_SECRET, algorithm="HS256")
            
            # Connect to LiveKit
            self.livekit_room = rtc.Room()
            await self.livekit_room.connect(LIVEKIT_URL, token)
            
            logger.info(f"[{self.stream_sid}] Connected to LiveKit as {self.livekit_room.local_participant.identity}")
            
            # Setup audio source (24kHz mono - matches orchestrator audio)
            self.audio_source = rtc.AudioSource(24000, 1)
            self.audio_track = rtc.LocalAudioTrack.create_audio_track(
                f"phone-{self.stream_sid}",
                self.audio_source
            )
            
            # Publish audio track
            await self.livekit_room.local_participant.publish_track(self.audio_track)
            logger.info(f"[{self.stream_sid}] Published audio track")
            
            # Subscribe to other participants' audio (the AI agent)
            self.livekit_room.on("track_subscribed", self._on_track_subscribed)
            self.livekit_room.on("track_unsubscribed", self._on_track_unsubscribed)
            self.livekit_room.on("participant_connected", self._on_participant_connected)
            self.livekit_room.on("participant_disconnected", self._on_participant_disconnected)
            
            # Check if agent is already in room and subscribe to their tracks
            for participant in self.livekit_room.remote_participants.values():
                if participant.identity != self.livekit_room.local_participant.identity:
                    logger.info(f"[{self.stream_sid}] Agent already in room: {participant.identity}")
                    # Subscribe to existing audio tracks
                    for publication in participant.track_publications.values():
                        if publication.kind == rtc.TrackKind.KIND_AUDIO:
                            logger.info(f"[{self.stream_sid}] Found audio track: {publication.sid}")
                            # The track might already be subscribed, check if track exists
                            if publication.track:
                                logger.info(f"[{self.stream_sid}] Track already available, forwarding to Twilio")
                                asyncio.create_task(self._forward_audio_to_twilio(publication.track))
            
            return True
            
        except Exception as e:
            logger.error(f"[{self.stream_sid}] Failed to connect to LiveKit: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _on_track_subscribed(self, track, publication, participant):
        """Handle when a track is subscribed"""
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"[{self.stream_sid}] Subscribed to audio from {participant.identity}")
            asyncio.create_task(self._forward_audio_to_twilio(track))
    
    def _on_track_unsubscribed(self, track, publication, participant):
        """Handle when a track is unsubscribed"""
        logger.info(f"[{self.stream_sid}] Unsubscribed from {participant.identity}")
        if self.subscribed_track == track:
            self.subscribed_track = None
    
    def _on_participant_connected(self, participant):
        """Handle when a participant joins"""
        logger.info(f"[{self.stream_sid}] Participant joined: {participant.identity}")
        # Subscribe to their audio track publications
        for publication in participant.track_publications.values():
            if publication.kind == rtc.TrackKind.KIND_AUDIO:
                # Actual track will come via track_subscribed event
                pass
    
    def _on_participant_disconnected(self, participant):
        """Handle when a participant leaves"""
        logger.info(f"[{self.stream_sid}] Participant left: {participant.identity}")
    
    async def _subscribe_to_track(self, track):
        """Subscribe to a specific track (deprecated - use _on_track_subscribed)"""
        # Track subscriptions now handled by _on_track_subscribed event
        pass
    
    async def _forward_audio_to_twilio(self, track):
        """
        Forward audio from LiveKit to Twilio
        LiveKit: 24kHz PCM → Convert to 8kHz PCM → mu-law → Twilio
        """
        try:
            audio_stream = rtc.AudioStream(track, sample_rate=24000, num_channels=1)
            
            # Use instance resample state for egress (AI -> Twilio)
            
            async for event in audio_stream:
                if self.twilio_ws and self.twilio_ws.state == websockets.State.OPEN:
                    try:
                        # event.frame contains the AudioFrame (24kHz)
                        frame = event.frame
                        
                        # Debug: log frame info with dtype
                        if self.frames_sent % 100 == 0:
                            # Check first few bytes to verify format
                            sample_bytes = bytes(frame.data[:10])
                            logger.info(f"[{self.stream_sid}] Frame: sr={frame.sample_rate}, samples={frame.samples_per_channel}, data_len={len(frame.data)}, first_bytes={sample_bytes.hex()}")
                        
                        # LiveKit AudioFrame data is already int16 (2 bytes per sample)
                        # Just convert memoryview to bytes for audioop
                        pcm_data = bytes(frame.data)
                        
                        # Convert 24kHz to 8kHz mono (stateful resampling)
                        pcm_8k, self.egress_resample_state = audioop.ratecv(pcm_data, 2, 1, 24000, 8000, self.egress_resample_state)
                        
                        # Convert PCM 16-bit to mu-law (Twilio format)
                        mulaw_data = audioop.lin2ulaw(pcm_8k, 2)
                        
                        # Debug: log mu-law output
                        if self.frames_sent % 100 == 0:
                            logger.info(f"[{self.stream_sid}] PCM 8k len: {len(pcm_8k)}, mu-law len: {len(mulaw_data)}, first_mu_bytes={mulaw_data[:10].hex()}")
                        
                        # Base64 encode
                        payload = base64.b64encode(mulaw_data).decode('utf-8')
                        
                        # Send to Twilio
                        message = {
                            "event": "media",
                            "streamSid": self.stream_sid,
                            "media": {
                                "payload": payload
                            }
                        }
                        await self.twilio_ws.send(json.dumps(message))
                        self.frames_sent += 1
                        
                    except Exception as e:
                        logger.error(f"[{self.stream_sid}] Error forwarding to Twilio: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        
        except Exception as e:
            logger.error(f"[{self.stream_sid}] Error in audio stream: {e}")
    
    async def handle_twilio_media(self, data):
        """
        Handle media from Twilio
        Twilio: mu-law 8kHz → PCM → resample to 48kHz → LiveKit
        """
        try:
            payload = base64.b64decode(data['media']['payload'])
            
            # Convert mu-law to PCM
            pcm_data = audioop.ulaw2lin(payload, 2)
            
            # Convert 8kHz to 24kHz (stateful resampling)
            pcm_24k, self.ingress_resample_state = audioop.ratecv(pcm_data, 2, 1, 8000, 24000, self.ingress_resample_state)
            
            # Create audio frame for LiveKit
            # LiveKit AudioFrame expects int16, not float32
            # pcm_24k is already int16 bytes, use directly
            audio_array = np.frombuffer(pcm_24k, dtype=np.int16)
            
            # Create and capture frame
            if self.audio_source:
                frame = rtc.AudioFrame(
                    data=audio_array.tobytes(),
                    sample_rate=24000,
                    num_channels=1,
                    samples_per_channel=len(audio_array)
                )
                await self.audio_source.capture_frame(frame)
                self.frames_received += 1
                
        except Exception as e:
            logger.error(f"[{self.stream_sid}] Error handling Twilio media: {e}")
    
    async def handle_message(self, message_data):
        """Handle messages from Twilio"""
        event = message_data.get('event')
        
        if event == 'start':
            logger.info(f"[{self.stream_sid}] Call started: {message_data['start']}")
            success = await self.connect_livekit()
            if success:
                # Send mark to acknowledge
                await self.twilio_ws.send(json.dumps({
                    "event": "mark",
                    "streamSid": self.stream_sid,
                    "mark": {"name": "connected"}
                }))
            
        elif event == 'media':
            await self.handle_twilio_media(message_data)
            
        elif event == 'mark':
            logger.info(f"[{self.stream_sid}] Mark received: {message_data}")
            
        elif event == 'stop':
            logger.info(f"[{self.stream_sid}] Call stopped")
            await self.cleanup()
            
        else:
            logger.debug(f"[{self.stream_sid}] Unknown event: {event}")
    
    async def cleanup(self):
        """Cleanup resources"""
        logger.info(f"[{self.stream_sid}] Cleaning up bridge")
        
        duration = time.time() - self.start_time
        logger.info(f"[{self.stream_sid}] Call duration: {duration:.1f}s, "
                   f"frames received: {self.frames_received}, sent: {self.frames_sent}")
        
        if self.livekit_room:
            try:
                await self.livekit_room.disconnect()
                logger.info(f"[{self.stream_sid}] Disconnected from LiveKit")
            except Exception as e:
                logger.error(f"[{self.stream_sid}] Error disconnecting: {e}")
        
        if self.stream_sid in active_calls:
            del active_calls[self.stream_sid]


# WebSocket server for Twilio Media Streams
async def handle_twilio_websocket(websocket):
    """
    Handle WebSocket connections from Twilio Media Streams
    (websockets 15.x API - single argument)
    """
    path = getattr(websocket.request, 'path', 'unknown') if hasattr(websocket, 'request') else 'unknown'
    logger.info(f"New WebSocket connection: {path}")
    bridge = None
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                event = data.get('event')
                
                if event == 'start':
                    stream_sid = data['start']['streamSid']
                    call_sid = data['start']['callSid']
                    from_number = data['start'].get('from', 'unknown')
                    
                    logger.info(f"Media stream started: {stream_sid} (call: {call_sid})")
                    
                    # Create bridge
                    bridge = TwilioLiveKitBridge(stream_sid, call_sid, from_number)
                    bridge.twilio_ws = websocket
                    active_calls[stream_sid] = bridge
                    
                    # Handle the start event
                    await bridge.handle_message(data)
                    
                elif bridge:
                    await bridge.handle_message(data)
                else:
                    logger.warning(f"Received {event} but no bridge exists")
                    
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received: {message[:100]}")
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"WebSocket closed: {path if 'path' in locals() else 'unknown'}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if bridge:
            await bridge.cleanup()


# Flask app for Twilio webhooks
flask_app = Flask(__name__)

@flask_app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return Response(json.dumps({
        "status": "healthy",
        "service": "twilio-media-bridge",
        "active_calls": len(active_calls),
        "livekit_url": LIVEKIT_URL,
        "room": ROOM_NAME
    }), mimetype='application/json')

@flask_app.route('/voice', methods=['POST'])
@flask_app.route('/twilio-voice', methods=['POST'])
def incoming_call():
    """
    Handle incoming Twilio call
    Returns TwiML to connect to Media Streams
    """
    call_sid = request.form.get('CallSid', 'unknown')
    from_number = request.form.get('From', 'unknown')
    
    logger.info(f"Incoming call: {call_sid} from {from_number}")
    
    # Create TwiML response
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Connecting you to DGX Spark Voice AI.</Say>
    <Connect>
        <Stream url="wss://cleans2s.voiceflow.cloud/twilio-media" />
    </Connect>
</Response>"""
    
    return Response(twiml, mimetype='text/xml')

@flask_app.route('/status', methods=['POST'])
def call_status():
    """Handle call status callbacks"""
    call_sid = request.form.get('CallSid')
    status = request.form.get('CallStatus')
    logger.info(f"Call {call_sid} status: {status}")
    return '', 204


def run_flask():
    """Run Flask in background thread"""
    logger.info(f"Starting Flask webhook server on port {TWILIO_WEBHOOK_PORT}")
    flask_app.run(host='0.0.0.0', port=TWILIO_WEBHOOK_PORT, debug=False, threaded=True)


async def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("Twilio ↔ LiveKit Media Bridge")
    logger.info("=" * 60)
    logger.info(f"LiveKit URL: {LIVEKIT_URL}")
    logger.info(f"Room: {ROOM_NAME}")
    logger.info(f"Webhook: http://0.0.0.0:{TWILIO_WEBHOOK_PORT}/twilio-voice")
    logger.info(f"Media Stream: ws://0.0.0.0:{MEDIA_STREAM_PORT}")
    logger.info("=" * 60)
    
    # Start Flask in background thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start WebSocket server for Twilio Media Streams
    logger.info(f"Starting WebSocket server on port {MEDIA_STREAM_PORT}")
    
    async with websockets.serve(
        handle_twilio_websocket, 
        "0.0.0.0", 
        MEDIA_STREAM_PORT,
        ping_interval=20,
        ping_timeout=10
    ):
        logger.info("WebSocket server started")
        logger.info("Ready for calls!")
        
        # Keep running
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
