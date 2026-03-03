#!/usr/bin/env python3
"""
Twilio ↔ LiveKit Bridge
=======================

Bridges audio between Twilio phone calls and LiveKit rooms.

Architecture:
Phone → Twilio → Media Streams (WebSocket) → This Bridge → LiveKit → Orchestrator

Requirements:
- pip install websockets flask livekit
- Twilio account with phone number
- LiveKit server running
"""

import asyncio
import websockets
import json
import base64
import logging
from flask import Flask, request, Response
from threading import Thread
import livekit
from livekit import rtc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
LIVEKIT_URL = "wss://cleans2s.voiceflow.cloud"
LIVEKIT_API_KEY = "APIQp4vjmCjrWQ9"
LIVEKIT_API_SECRET = "PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l"
ROOM_NAME = "dgx-spark-room"

# Store active bridges
active_bridges = {}


class TwilioLiveKitBridge:
    """Bridges audio between Twilio Media Stream and LiveKit"""
    
    def __init__(self, call_sid, from_number):
        self.call_sid = call_sid
        self.from_number = from_number
        self.twilio_ws = None
        self.livekit_room = None
        self.audio_source = None
        self.audio_track = None
        
    async def connect_livekit(self):
        """Connect to LiveKit room"""
        try:
            # Generate token
            token = self._generate_token()
            
            # Connect to room
            self.livekit_room = livekit.Room()
            await self.livekit_room.connect(LIVEKIT_URL, token)
            
            logger.info(f"Bridge {self.call_sid}: Connected to LiveKit room {ROOM_NAME}")
            
            # Setup audio publication
            self.audio_source = rtc.AudioSource(8000, 1)  # Twilio uses 8kHz
            self.audio_track = rtc.LocalAudioTrack.create_audio_track(
                f"twilio-{self.call_sid}",
                self.audio_source
            )
            
            await self.livekit_room.local_participant.publish_track(self.audio_track)
            
            # Subscribe to agent audio
            self.livekit_room.on("track_subscribed", self._on_track_subscribed)
            
            return True
            
        except Exception as e:
            logger.error(f"Bridge {self.call_sid}: Failed to connect to LiveKit: {e}")
            return False
    
    def _generate_token(self):
        """Generate LiveKit token"""
        import jwt
        from datetime import datetime, timedelta
        
        now = datetime.utcnow()
        payload = {
            "exp": now + timedelta(hours=1),
            "iss": LIVEKIT_API_KEY,
            "sub": f"twilio-{self.call_sid}",
            "nbf": now,
            "video": {
                "roomJoin": True,
                "room": ROOM_NAME,
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": True
            }
        }
        return jwt.encode(payload, LIVEKIT_API_SECRET, algorithm="HS256")
    
    def _on_track_subscribed(self, track, publication, participant):
        """Handle agent audio"""
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"Bridge {self.call_sid}: Subscribed to agent audio")
            # Forward agent audio back to Twilio
            asyncio.create_task(self._forward_to_twilio(track))
    
    async def _forward_to_twilio(self, track):
        """Forward LiveKit audio to Twilio"""
        audio_stream = rtc.AudioStream(track)
        async for frame in audio_stream:
            if self.twilio_ws and self.twilio_ws.open:
                # Convert LiveKit audio to Twilio format (mulaw)
                # This is simplified - you'd need proper audio conversion
                audio_data = self._convert_to_mulaw(frame.data)
                
                message = {
                    "event": "media",
                    "streamSid": self.call_sid,
                    "media": {
                        "payload": base64.b64encode(audio_data).decode()
                    }
                }
                await self.twilio_ws.send(json.dumps(message))
    
    def _convert_to_mulaw(self, pcm_data):
        """Convert PCM to mu-law (Twilio format)"""
        # Simplified - use proper audio conversion library in production
        # e.g., pydub, audioop, etc.
        return pcm_data  # Placeholder
    
    async def handle_twilio_message(self, message):
        """Handle message from Twilio"""
        data = json.loads(message)
        event = data.get('event')
        
        if event == 'start':
            logger.info(f"Bridge {self.call_sid}: Call started")
            await self.connect_livekit()
            
        elif event == 'media':
            # Audio from caller
            payload = base64.b64decode(data['media']['payload'])
            # Convert mulaw to PCM and send to LiveKit
            pcm_data = self._convert_from_mulaw(payload)
            
            if self.audio_source:
                # Create audio frame and capture
                frame = rtc.AudioFrame(
                    data=pcm_data,
                    sample_rate=8000,
                    num_channels=1,
                    samples_per_channel=len(pcm_data) // 2
                )
                await self.audio_source.capture_frame(frame)
                
        elif event == 'stop':
            logger.info(f"Bridge {self.call_sid}: Call ended")
            await self.cleanup()
    
    def _convert_from_mulaw(self, mulaw_data):
        """Convert mu-law to PCM"""
        # Simplified - use proper audio conversion in production
        import audioop
        return audioop.ulaw2lin(mulaw_data, 2)
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.livekit_room:
            await self.livekit_room.disconnect()
        if self.call_sid in active_bridges:
            del active_bridges[self.call_sid]


# WebSocket handler for Twilio Media Streams
async def handle_twilio_stream(websocket, path):
    """Handle WebSocket connection from Twilio"""
    logger.info(f"New Twilio WebSocket connection: {path}")
    
    bridge = None
    
    try:
        async for message in websocket:
            data = json.loads(message)
            event = data.get('event')
            
            if event == 'start':
                call_sid = data['start']['callSid']
                from_number = data['start'].get('from', 'unknown')
                
                logger.info(f"Call started: {call_sid} from {from_number}")
                
                # Create bridge
                bridge = TwilioLiveKitBridge(call_sid, from_number)
                bridge.twilio_ws = websocket
                active_bridges[call_sid] = bridge
                
                # Send mark to acknowledge
                await websocket.send(json.dumps({
                    "event": "mark",
                    "streamSid": call_sid,
                    "mark": {"name": "connected"}
                }))
                
            elif bridge:
                await bridge.handle_twilio_message(message)
                
    except websockets.exceptions.ConnectionClosed:
        logger.info("Twilio WebSocket closed")
    except Exception as e:
        logger.error(f"Error handling Twilio stream: {e}")
    finally:
        if bridge:
            await bridge.cleanup()


# Flask app for Twilio webhooks
flask_app = Flask(__name__)

@flask_app.route('/voice', methods=['POST'])
def incoming_call():
    """Handle incoming Twilio call"""
    call_sid = request.form.get('CallSid', 'unknown')
    from_number = request.form.get('From', 'unknown')
    
    logger.info(f"Incoming call webhook: {call_sid} from {from_number}")
    
    # Return TwiML to start Media Stream
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Connecting you to DGX Spark Voice AI.</Say>
    <Connect>
        <Stream url="wss://cleans2s.voiceflow.cloud/twilio-stream" track="both_tracks" />
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
    """Run Flask in separate thread"""
    flask_app.run(host='0.0.0.0', port=5000, debug=False)


async def main():
    """Main function"""
    logger.info("Starting Twilio-LiveKit Bridge")
    
    # Start Flask in background thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask webhook server started on port 5000")
    
    # Start WebSocket server for Twilio Media Streams
    async with websockets.serve(handle_twilio_stream, "0.0.0.0", 5001):
        logger.info("WebSocket server started on port 5001")
        logger.info("Twilio webhook URL: https://twilio-bridge.voiceflow.cloud/voice")
        logger.info("WebSocket URL: wss://cleans2s.voiceflow.cloud/twilio-stream")
        
        # Keep running
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
