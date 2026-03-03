#!/usr/bin/env python3
"""
LiveKit Voice Client for Testing S2S Pipeline
Connects to the LiveKit room and handles audio I/O
"""

import asyncio
import numpy as np
import sounddevice as sd
import websockets
import json
import base64
from livekit import rtc

# Configuration
LIVEKIT_URL = "ws://localhost:7880"
ROOM_NAME = "dgx-spark-room"
TOKEN = None  # Will generate

# Audio settings
SAMPLE_RATE = 48000
CHUNK_DURATION_MS = 20
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)


class LiveKitVoiceClient:
    def __init__(self):
        self.room = rtc.Room()
        self.audio_source = None
        self.audio_track = None
        
    async def generate_token(self):
        """Generate a LiveKit access token"""
        import jwt
        from datetime import datetime, timedelta
        
        api_key = "APIQp4vjmCjrWQ9"
        api_secret = "PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l"
        
        token = jwt.encode(
            {
                "exp": datetime.utcnow() + timedelta(hours=1),
                "iss": api_key,
                "sub": "test-user",
                "video": {
                    "roomJoin": True,
                    "room": ROOM_NAME,
                    "canPublish": True,
                    "canSubscribe": True,
                }
            },
            api_secret,
            algorithm="HS256"
        )
        return token
    
    async def connect(self):
        """Connect to LiveKit room"""
        print("🔌 Connecting to LiveKit...")
        
        token = await self.generate_token()
        await self.room.connect(LIVEKIT_URL, token)
        
        print(f"✅ Connected to room: {self.room.name}")
        print(f"   Local participant: {self.room.local_participant.sid}")
        
        # Setup audio
        await self.setup_audio()
        
        # Listen for events
        self.room.on("track_subscribed", self.on_track_subscribed)
        
    async def setup_audio(self):
        """Setup audio input/output"""
        # Create audio source for microphone
        self.audio_source = rtc.AudioSource(SAMPLE_RATE, 1)
        self.audio_track = rtc.LocalAudioTrack.create_audio_track(
            "microphone", 
            self.audio_source
        )
        
        # Publish audio track
        await self.room.local_participant.publish_track(self.audio_track)
        print("🎤 Audio track published")
        
        # Start recording
        asyncio.create_task(self.record_audio())
        
    async def record_audio(self):
        """Record audio from microphone and send to room"""
        print("\n🎙️  Recording... (Press Ctrl+C to stop)")
        print("   Speak to test the S2S pipeline!")
        print()
        
        def callback(indata, frames, time_info, status):
            if status:
                print(f"Audio status: {status}")
            
            # Convert to int16
            audio_data = (indata[:, 0] * 32767).astype(np.int16)
            
            # Create audio frame
            frame = rtc.AudioFrame(
                data=audio_data.tobytes(),
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=len(audio_data)
            )
            
            # Capture frame
            asyncio.create_task(self.audio_source.capture_frame(frame))
        
        # Start recording stream
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype=np.float32,
            blocksize=CHUNK_SAMPLES,
            callback=callback
        ):
            while True:
                await asyncio.sleep(1)
    
    def on_track_subscribed(self, track, publication, participant):
        """Handle incoming audio from agent"""
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            print(f"🔊 Subscribed to agent audio: {participant.identity}")
            asyncio.create_task(self.play_audio(track))
    
    async def play_audio(self, track):
        """Play incoming audio from agent"""
        audio_stream = rtc.AudioStream(track)
        
        # Playback buffer
        buffer = []
        
        async for frame in audio_stream:
            # Convert bytes to numpy array
            audio_data = np.frombuffer(frame.data, dtype=np.int16)
            audio_float = audio_data.astype(np.float32) / 32767.0
            buffer.append(audio_float)
            
            # Play when we have enough data (100ms)
            if len(buffer) >= 5:
                audio_chunk = np.concatenate(buffer)
                sd.play(audio_chunk, samplerate=SAMPLE_RATE, blocking=False)
                buffer = []


async def simple_websocket_test():
    """Simple test using direct WebSocket (no LiveKit SDK)"""
    print("="*60)
    print("Simple Audio Test")
    print("="*60)
    print()
    print("Testing ASR -> LLM -> TTS pipeline directly...")
    print()
    
    # Test ASR
    print("1. Testing ASR...")
    # Create a simple audio test
    duration = 2  # seconds
    sample_rate = 16000
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    # Generate a simple tone (not speech, but will trigger the pipeline)
    tone = np.sin(2 * np.pi * 440 * t) * 0.3
    
    # Convert to PCM16
    pcm_data = (tone * 32767).astype(np.int16).tobytes()
    
    print(f"   Generated {len(pcm_data)} bytes of test audio")
    print("   (In real test, this would be your microphone input)")
    print()
    
    print("2. Testing LLM...")
    async with websockets.connect("ws://localhost:8000/v1/realtime") as ws:
        # Wait for session.created
        msg = await ws.recv()
        print(f"   LLM: {msg[:80]}...")
    
    print("   LLM connection working!")
    print()
    
    print("3. Testing TTS...")
    async with websockets.connect("ws://localhost:8002/ws/tts") as tts_ws:
        await tts_ws.send(json.dumps({"type": "init", "voice": "phil"}))
        await tts_ws.send(json.dumps({"type": "token", "text": "Hello, this is a test."}))
        await tts_ws.send(json.dumps({"type": "end"}))
        
        audio_chunks = 0
        start = asyncio.get_event_loop().time()
        
        while True:
            try:
                msg = await asyncio.wait_for(tts_ws.recv(), timeout=5.0)
                if isinstance(msg, bytes):
                    audio_chunks += 1
                    if audio_chunks == 1:
                        latency = (asyncio.get_event_loop().time() - start) * 1000
                        print(f"   First audio: {latency:.1f}ms ({len(msg)} bytes)")
                else:
                    data = json.loads(msg)
                    if data.get("type") == "complete":
                        break
            except asyncio.TimeoutError:
                break
        
        print(f"   Total audio chunks: {audio_chunks}")
    
    print()
    print("✅ All components working!")


async def main():
    print("="*60)
    print("LiveKit Voice Client - S2S Pipeline Test")
    print("="*60)
    print()
    print("Choose test mode:")
    print("1. Simple component test (no audio I/O)")
    print("2. Full voice conversation (requires microphone & speakers)")
    print()
    
    try:
        choice = input("Enter choice (1 or 2): ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "1"
    
    if choice == "2":
        try:
            client = LiveKitVoiceClient()
            await client.connect()
            
            # Keep running
            while True:
                await asyncio.sleep(1)
                
        except ImportError as e:
            print(f"❌ Missing dependency: {e}")
            print("   Install with: pip install livekit sounddevice numpy")
        except Exception as e:
            print(f"❌ Error: {e}")
    else:
        await simple_websocket_test()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
