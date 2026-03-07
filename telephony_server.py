#!/usr/bin/env python3
"""
Native Logic Telephony Server
FastAPI + WebSocket server for Twilio integration

Production-ready with:
- Proper Twilio webhook handling
- Stream SID tracking
- Concurrent call support
- Health monitoring
- Metrics collection
"""

import asyncio
import base64
import json
import io
import wave
import audioop
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional, Set
from datetime import datetime
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Form
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
import aiohttp
import uvicorn

# Configuration
BRAIN_URL = "http://localhost:8000/v1/chat/completions"
EAR_URL = "http://localhost:8001/v1/chat/completions"
VOICE_URL = "http://localhost:8002/v1/audio/speech"

# Audio settings
TWILIO_RATE = 8000
TARGET_RATE = 16000
BYTES_PER_SAMPLE = 2
SILENCE_THRESHOLD = 0.01
MIN_UTTERANCE_MS = 500
MAX_UTTERANCE_MS = 10000
CHUNK_DURATION_MS = 20  # Twilio sends 20ms chunks


# ============== Data Models ==============

class TwilioWebhookRequest(BaseModel):
    """Incoming call webhook from Twilio."""
    CallSid: str
    From: str
    To: str
    CallStatus: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    brain: bool
    ear: bool
    voice: bool
    active_calls: int


@dataclass
class Speaker:
    """Speaker in conversation."""
    speaker_id: str
    first_seen: datetime
    last_seen: datetime
    utterance_count: int = 0


@dataclass
class CallSession:
    """State for a single call."""
    call_sid: str
    stream_sid: Optional[str] = None
    websocket: Optional[WebSocket] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    speakers: Dict[str, Speaker] = field(default_factory=dict)
    current_speaker: Optional[str] = None
    speaker_counter: int = 0
    
    history: deque = field(default_factory=lambda: deque(maxlen=20))
    system_prompt: str = """You are Phil, a helpful AI assistant on a phone call. Be warm, conversational, and natural. Use occasional verbal fillers ("um", "ah", "well"). Keep responses to 1-2 sentences for phone conversations. You can identify different speakers."""
    
    audio_buffer: bytearray = field(default_factory=bytearray)
    silence_duration_ms: float = 0.0
    is_processing: bool = False
    
    total_turns: int = 0
    total_latency_ms: float = 0.0
    
    def get_or_create_speaker(self, speaker_hint: Optional[str] = None) -> Speaker:
        if speaker_hint and speaker_hint in self.speakers:
            return self.speakers[speaker_hint]
        
        self.speaker_counter += 1
        speaker_id = f"speaker_{self.speaker_counter}"
        now = datetime.now()
        speaker = Speaker(speaker_id=speaker_id, first_seen=now, last_seen=now)
        self.speakers[speaker_id] = speaker
        self.current_speaker = speaker_id
        return speaker
    
    def add_turn(self, speaker_id: str, text: str, emotion: Optional[str] = None):
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "speaker": speaker_id,
            "text": text,
            "emotion": emotion
        })
        if speaker_id in self.speakers:
            self.speakers[speaker_id].utterance_count += 1
            self.speakers[speaker_id].last_seen = datetime.now()
        self.total_turns += 1
    
    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(self.total_turns, 1)


# ============== Audio Processor ==============

class AudioProcessor:
    """Audio format conversions."""
    
    @staticmethod
    def ulaw_to_pcm(ulaw_data: bytes) -> bytes:
        return audioop.ulaw2lin(ulaw_data, 2)
    
    @staticmethod
    def pcm_to_ulaw(pcm_data: bytes) -> bytes:
        return audioop.lin2ulaw(pcm_data, 2)
    
    @staticmethod
    def resample_8k_to_16k(pcm_8k: bytes) -> bytes:
        return audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)[0]
    
    @staticmethod
    def resample_16k_to_8k(pcm_16k: bytes) -> bytes:
        return audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)[0]
    
    @staticmethod
    def bytes_to_numpy(pcm_bytes: bytes) -> np.ndarray:
        return np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    
    @staticmethod
    def calculate_energy(pcm_bytes: bytes) -> float:
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return np.abs(audio).mean()


# ============== Orchestrator ==============

class TelephonyOrchestrator:
    """Main orchestrator managing all calls."""
    
    def __init__(self):
        self.sessions: Dict[str, CallSession] = {}
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.audio_processor = AudioProcessor()
        
    async def start(self):
        """Initialize HTTP session."""
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60, connect=10),
            headers={"Content-Type": "application/json"}
        )
        # Load voice cloning reference audio
        import base64
        try:
            with open("/home/phil/telephony-stack/tts/phil-conversational-16k.wav", "rb") as f:
                self.phil_voice_audio = base64.b64encode(f.read()).decode()
            print(f"🎙️  Phil's voice loaded ({len(self.phil_voice_audio)} chars base64)")
        except Exception as e:
            print(f"⚠️  Could not load Phil's voice: {e}")
            self.phil_voice_audio = None
        print("🚀 Telephony Orchestrator initialized")
        
    async def stop(self):
        """Cleanup."""
        if self.http_session:
            await self.http_session.close()
    
    def create_session(self, call_sid: str) -> CallSession:
        """Create new call session."""
        session = CallSession(call_sid=call_sid)
        self.sessions[call_sid] = session
        print(f"📞 New call: {call_sid}")
        return session
    
    def get_session(self, call_sid: str) -> Optional[CallSession]:
        return self.sessions.get(call_sid)
    
    def remove_session(self, call_sid: str):
        if call_sid in self.sessions:
            session = self.sessions[call_sid]
            print(f"📴 Call ended: {call_sid} | "
                  f"Turns: {session.total_turns}, "
                  f"Avg latency: {session.avg_latency_ms:.0f}ms")
            del self.sessions[call_sid]
    
    async def health_check(self) -> dict:
        """Check all services."""
        results = {}
        
        for name, url in [
            ("brain", "http://localhost:8000/health"),
            ("ear", "http://localhost:8001/health"),
            ("voice", "http://localhost:8002/health"),
        ]:
            try:
                async with self.http_session.get(url, timeout=5) as resp:
                    results[name] = resp.status == 200
            except:
                results[name] = False
        
        return {
            **results,
            "active_calls": len(self.sessions)
        }
    
    async def process_audio_chunk(self, call_sid: str, ulaw_chunk: bytes) -> Optional[dict]:
        """Process incoming audio chunk."""
        session = self.sessions.get(call_sid)
        if not session or session.is_processing:
            return None
        
        # Convert audio
        pcm_8k = self.audio_processor.ulaw_to_pcm(ulaw_chunk)
        pcm_16k = self.audio_processor.resample_8k_to_16k(pcm_8k)
        
        # Add to buffer
        session.audio_buffer.extend(pcm_16k)
        
        # Energy-based silence detection
        energy = self.audio_processor.calculate_energy(pcm_16k)
        buffer_duration_ms = len(session.audio_buffer) / (TARGET_RATE * BYTES_PER_SAMPLE) * 1000
        
        if energy < SILENCE_THRESHOLD:
            session.silence_duration_ms += CHUNK_DURATION_MS
        else:
            session.silence_duration_ms = 0
        
        # Check if ready to process
        should_process = (
            (buffer_duration_ms >= MIN_UTTERANCE_MS and session.silence_duration_ms > 300) or
            buffer_duration_ms >= MAX_UTTERANCE_MS
        )
        
        if should_process and len(session.audio_buffer) > 1000:  # Min 1000 bytes
            audio_to_process = bytes(session.audio_buffer)
            session.audio_buffer = bytearray()
            session.silence_duration_ms = 0
            session.is_processing = True
            
            try:
                result = await self._process_utterance(session, audio_to_process)
                return result
            finally:
                session.is_processing = False
        
        return None
    
    async def _process_utterance(self, session: CallSession, pcm_16k: bytes) -> Optional[dict]:
        """Full pipeline: Ear -> Brain -> Voice."""
        start_time = time.time()
        
        try:
            # === STEP 1: EAR (Diarization + Transcription + Emotion) ===
            print(f"👂 [{session.call_sid[:16]}...] Processing...")
            
            # Create WAV for Omni
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(TARGET_RATE)
                wav.writeframes(pcm_16k)
            
            audio_b64 = base64.b64encode(wav_buffer.getvalue()).decode()
            
            ear_payload = {
                "model": "Qwen/Qwen2.5-Omni-7B",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe this and identify the speaker. Format: Speaker X: \"text\" (emotion if any)"},
                        {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}}
                    ]
                }],
                "max_tokens": 100,
                "temperature": 0.0
            }
            
            async with self.http_session.post(EAR_URL, json=ear_payload) as resp:
                if resp.status != 200:
                    print(f"   ❌ Ear error: {resp.status}")
                    return None
                ear_result = await resp.json()
                ear_text = ear_result['choices'][0]['message']['content']
            
            print(f"   📝 {ear_text[:80]}...")
            
            # Parse
            speaker_id, transcription, emotion = self._parse_ear_output(ear_text, session)
            session.add_turn(speaker_id, transcription, emotion)
            
            # === STEP 2: BRAIN (Response) ===
            messages = [{"role": "system", "content": session.system_prompt}]
            
            # Add multi-speaker context
            if len(session.speakers) > 1:
                speakers_ctx = "Speakers: " + ", ".join(
                    [f"{s.speaker_id}({s.utterance_count} turns)" for s in session.speakers.values()]
                )
                messages.append({"role": "system", "content": speakers_ctx})
            
            # Add history
            for turn in list(session.history)[-8:]:
                role = "assistant" if turn["speaker"] == "assistant" else "user"
                content = turn["text"]
                if turn.get("emotion"):
                    content += f" (sounds {turn['emotion']})"
                messages.append({"role": role, "content": content})
            
            brain_payload = {
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": messages,
                "max_tokens": 60,  # Short for telephony
                "temperature": 0.8
            }
            
            async with self.http_session.post(BRAIN_URL, json=brain_payload) as resp:
                if resp.status != 200:
                    print(f"   ❌ Brain error: {resp.status}")
                    return None
                brain_result = await resp.json()
                response_text = brain_result['choices'][0]['message']['content']
            
            print(f"   💬 {response_text[:80]}...")
            session.add_turn("assistant", response_text)
            
            # === STEP 3: VOICE (TTS) ===
            voice_payload = {
                "input": response_text,
                "voice": "phil",
                "speed": 1.0,
                "response_format": "wav",
                "extra_body": {
                    "reference_audio": self.phil_voice_audio,
                    "reference_text": "I really didn't expect the weather to change so quickly."
                } if self.phil_voice_audio else None
            }
            
            async with self.http_session.post(VOICE_URL, json=voice_payload) as resp:
                if resp.status != 200:
                    print(f"   ❌ Voice error: {resp.status}")
                    return None
                voice_audio = await resp.read()
            
            # Convert to Twilio format
            ulaw_audio = self._convert_voice_output(voice_audio)
            
            # Stats
            latency = (time.time() - start_time) * 1000
            session.total_latency_ms += latency
            
            print(f"   ✅ {latency:.0f}ms (avg: {session.avg_latency_ms:.0f}ms)")
            
            return {
                "audio_ulaw": base64.b64encode(ulaw_audio).decode(),
                "text": response_text,
                "speaker": speaker_id,
                "emotion": emotion,
                "latency_ms": latency
            }
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return None
    
    def _parse_ear_output(self, text: str, session: CallSession):
        """Parse Ear output for speaker, transcription, emotion."""
        import re
        
        # Extract speaker
        speaker_match = re.search(r'Speaker\s*(\d+)', text, re.IGNORECASE)
        if speaker_match:
            speaker_id = f"speaker_{speaker_match.group(1)}"
            if speaker_id not in session.speakers:
                session.get_or_create_speaker(speaker_id)
        else:
            speaker_id = session.current_speaker or session.get_or_create_speaker().speaker_id
        
        session.current_speaker = speaker_id
        
        # Extract transcription (between quotes)
        quote_match = re.search(r'"([^"]+)"', text)
        if quote_match:
            transcription = quote_match.group(1)
        else:
            # Fallback: remove speaker markers
            transcription = re.sub(r'Speaker\s*\d+:?', '', text, flags=re.IGNORECASE).strip('"').strip()
        
        # Extract emotion
        emotion_match = re.search(r'\(([^)]+)\)', text)
        emotion = None
        if emotion_match:
            emotion_text = emotion_match.group(1).lower()
            emotions = ['happy', 'sad', 'angry', 'frustrated', 'excited', 'calm', 'neutral', 'concerned']
            for e in emotions:
                if e in emotion_text:
                    emotion = e
                    break
        
        return speaker_id, transcription, emotion
    
    def _convert_voice_output(self, wav_data: bytes) -> bytes:
        """Convert 24kHz WAV to 8kHz μ-law."""
        wav_buf = io.BytesIO(wav_data)
        with wave.open(wav_buf, 'rb') as wav:
            pcm = wav.readframes(wav.getnframes())
            rate = wav.getframerate()
        
        # 24kHz -> 16kHz -> 8kHz
        pcm_16k = audioop.ratecv(pcm, 2, 1, rate, 16000, None)[0]
        pcm_8k = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)[0]
        
        return audioop.lin2ulaw(pcm_8k, 2)
    
    async def synthesize_greeting(self) -> Optional[bytes]:
        """Generate greeting audio with Phil's voice."""
        greeting = "Hello! Phil here from Native Logic. How can I help you?"
        
        # Use "phil" voice - the voice server has pre-cached embedding!
        # This is fast because the server already computed the speaker embedding
        voice_payload = {
            "input": greeting,
            "voice": "phil",  # Uses pre-cached embedding in voice server
            "speed": 1.0,
            "response_format": "wav"
        }
        
        try:
            print(f"   🎙️  Generating Phil's greeting...")
            async with self.http_session.post(VOICE_URL, json=voice_payload, timeout=30) as resp:
                if resp.status == 200:
                    audio = await resp.read()
                    print(f"   🎙️  Phil's greeting ready: {len(audio)} bytes")
                    return self._convert_voice_output(audio)
                else:
                    error_text = await resp.text()
                    print(f"   ❌ Voice error {resp.status}: {error_text[:200]}")
        except Exception as e:
            print(f"   ❌ Greeting failed: {type(e).__name__}: {e}")
        return None


# ============== FastAPI App ==============

orchestrator = TelephonyOrchestrator()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan management."""
    await orchestrator.start()
    yield
    await orchestrator.stop()

app = FastAPI(title="Native Logic Telephony", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    status = await orchestrator.health_check()
    return HealthResponse(
        status="healthy" if all([status["brain"], status["ear"], status["voice"]]) else "degraded",
        brain=status["brain"],
        ear=status["ear"],
        voice=status["voice"],
        active_calls=status["active_calls"]
    )


@app.post("/twilio/inbound")
async def twilio_inbound(
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    CallStatus: str = Form(...)
):
    """Handle incoming call from Twilio.
    
    Twilio sends form-encoded data (application/x-www-form-urlencoded)
    """
    print(f"📞 Inbound call: {CallSid} from {From}")
    
    # Create session
    orchestrator.create_session(CallSid)
    
    # Return TwiML to connect to WebSocket stream
    # Use the public WebSocket URL
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://cleans2s.voiceflow.cloud/twilio/stream" />
    </Connect>
</Response>"""
    
    return PlainTextResponse(content=twiml, media_type="application/xml")


@app.websocket("/twilio/stream")
async def twilio_websocket(websocket: WebSocket):
    """WebSocket for audio streaming."""
    await websocket.accept()
    print("🔌 Twilio WebSocket connected")
    
    call_sid = None
    stream_sid = None
    
    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event = data.get('event')
            
            if event == 'start':
                call_sid = data['start']['callSid']
                stream_sid = data['start']['streamSid']
                print(f"   📞 Call {call_sid[:20]}... started, streamSid: {stream_sid[:20]}...")
                
                session = orchestrator.get_session(call_sid)
                if session:
                    session.stream_sid = stream_sid
                    session.websocket = websocket
                    print(f"   ✅ Session attached")
                    
                    # Send greeting
                    print(f"   🎙️  Generating greeting...")
                    greeting_audio = await orchestrator.synthesize_greeting()
                    print(f"   🎙️  Greeting audio: {len(greeting_audio) if greeting_audio else 0} bytes")
                    if greeting_audio:
                        await websocket.send_json({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": base64.b64encode(greeting_audio).decode()}
                        })
                        # Add to history
                        session.add_turn("assistant", "Hello! Phil here from Native Logic. How can I help you?")
                
            elif event == 'media':
                if not call_sid:
                    print("   ⚠️  Media event but no call_sid")
                    continue
                
                # Decode audio
                payload = data['media']['payload']
                ulaw_chunk = base64.b64decode(payload)
                print(f"   🎵 Received audio chunk: {len(ulaw_chunk)} bytes")
                
                # Process
                result = await orchestrator.process_audio_chunk(call_sid, ulaw_chunk)
                
                if result and stream_sid:
                    # Send response
                    await websocket.send_json({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": result['audio_ulaw']}
                    })
                    
            elif event == 'stop':
                print(f"   📴 Call ended")
                if call_sid:
                    orchestrator.remove_session(call_sid)
                break
                
    except WebSocketDisconnect:
        print("🔌 WebSocket disconnected")
        if call_sid:
            orchestrator.remove_session(call_sid)
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        if call_sid:
            orchestrator.remove_session(call_sid)


@app.get("/calls")
async def list_calls():
    """List active calls."""
    return {
        "active_calls": len(orchestrator.sessions),
        "calls": [
            {
                "call_sid": s.call_sid,
                "duration_seconds": (datetime.now() - s.created_at).seconds,
                "turns": s.total_turns,
                "speakers": len(s.speakers),
                "avg_latency_ms": s.avg_latency_ms
            }
            for s in orchestrator.sessions.values()
        ]
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
