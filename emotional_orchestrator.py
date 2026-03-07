#!/usr/bin/env python3
"""
Emotional Metadata Bridge - Main Orchestrator
Coordinates ASR (emotion extraction) -> Brain (emotional reasoning) -> TTS (voice emotion)

Architecture:
1. ASR (Port 8001): Qwen2.5-Omni extracts [USER_EMOTION] from audio
2. Brain (Port 8000): Qwen3.5-9B reasons with emotion, outputs <RESPONSE_EMOTION>
3. TTS (Port 8002): MOSS-TTS-Realtime clones voice with emotional reference

Emotion Flow:
[User Audio] -> [ASR: FRUSTRATED] -> [Brain: <EMPATHETIC>] -> [TTS: empathetic voice]
"""

import os
import io
import base64
import audioop
import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import PlainTextResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== Configuration ==============

ASR_URL = "http://localhost:8001/v1/audio/transcriptions"
BRAIN_URL = "http://localhost:8000/v1/chat/completions"
TTS_URL = "http://localhost:8002/v1/audio/speech"

# Audio settings
TARGET_RATE = 16000
SILENCE_THRESHOLD = 0.01
MIN_UTTERANCE_MS = 500
MAX_UTTERANCE_MS = 8000

# Emotion mapping: User emotion -> Response emotion -> Voice emotion
EMOTION_CHAIN = {
    "FRUSTRATED": {"response": "EMPATHETIC", "voice": "empathetic"},
    "JOYFUL": {"response": "CHEERFUL", "voice": "cheerful"},
    "HESITANT": {"response": "THINKING", "voice": "thinking"},
    "URGENT": {"response": "URGENT", "voice": "urgent"},
    "CONFUSED": {"response": "EMPATHETIC", "voice": "empathetic"},
    "NEUTRAL": {"response": "NEUTRAL", "voice": "neutral"},
}

# ============== Audio Processor ==============

class AudioProcessor:
    """Audio format conversions for telephony."""
    
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
    def resample_24k_to_ulaw(pcm_24k: bytes) -> bytes:
        """Resample 24kHz (MOSS-TTS output) to 8kHz μ-law for Twilio."""
        pcm_16k = audioop.ratecv(pcm_24k, 2, 1, 24000, 16000, None)[0]
        pcm_8k = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)[0]
        return audioop.lin2ulaw(pcm_8k, 2)
    
    @staticmethod
    def calculate_energy(pcm_bytes: bytes) -> float:
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return np.abs(audio).mean()

# ============== Session Management ==============

@dataclass
class CallSession:
    """Active call session state."""
    call_sid: str
    stream_sid: Optional[str] = None
    websocket: Optional[WebSocket] = None
    created_at: datetime = field(default_factory=datetime.now)
    history: deque = field(default_factory=lambda: deque(maxlen=10))
    audio_buffer: bytearray = field(default_factory=bytearray)
    silence_duration_ms: float = 0.0
    is_processing: bool = False
    last_user_emotion: str = "NEUTRAL"
    
    system_prompt: str = """You are Phil, a helpful and empathetic AI assistant. 
Respond naturally with emotional intelligence. Be warm, concise, and human."""

# ============== Emotional Orchestrator ==============

class EmotionalOrchestrator:
    """
    Orchestrates the full S2S pipeline with emotional metadata bridging.
    
    Flow:
    1. Receive audio from Twilio
    2. ASR extracts: [USER_EMOTION] "transcription"
    3. Brain receives user_emotion, generates: <RESPONSE_EMOTION> "response"
    4. TTS uses voice matching RESPONSE_EMOTION
    5. Audio streamed back to Twilio
    """
    
    def __init__(self):
        self.sessions: dict[str, CallSession] = {}
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.audio_processor = AudioProcessor()
        
    async def start(self):
        """Initialize HTTP session."""
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
            headers={"Content-Type": "application/json"}
        )
        
        # Check service health
        await self._check_services()
        
        logger.info("🚀 Emotional Orchestrator initialized")
        logger.info("   ASR: http://localhost:8001 (emotion extraction)")
        logger.info("   Brain: http://localhost:8000 (emotional reasoning)")
        logger.info("   TTS: http://localhost:8002 (emotional voice)")
        
    async def stop(self):
        """Cleanup."""
        if self.http_session:
            await self.http_session.close()
            
    async def _check_services(self):
        """Check if all services are running."""
        services = [
            ("ASR", "http://localhost:8001/health"),
            ("Brain", "http://localhost:8000/health"),
            ("TTS", "http://localhost:8002/health"),
        ]
        
        for name, url in services:
            try:
                async with self.http_session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"✅ {name} ready: {data}")
                    else:
                        logger.warning(f"⚠️ {name} returned {resp.status}")
            except Exception as e:
                logger.error(f"❌ {name} unavailable: {e}")
    
    def create_session(self, call_sid: str) -> CallSession:
        """Create new call session."""
        session = CallSession(call_sid=call_sid)
        self.sessions[call_sid] = session
        return session
        
    def get_session(self, call_sid: str) -> Optional[CallSession]:
        return self.sessions.get(call_sid)
        
    def remove_session(self, call_sid: str):
        self.sessions.pop(call_sid, None)
    
    # ===== ASR with Emotion Extraction =====
    
    async def transcribe_with_emotion(self, pcm_16k: bytes) -> tuple[str, str]:
        """
        Transcribe audio and extract emotion.
        
        Returns:
            (emotion, text) tuple
        """
        try:
            # Create WAV from PCM
            import wave
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm_16k)
            
            audio_b64 = base64.b64encode(wav_buffer.getvalue()).decode()
            
            # Call emotion-aware ASR
            payload = {
                "audio": audio_b64,
                "format": "wav",
                "language": "en"
            }
            
            async with self.http_session.post(ASR_URL, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    emotion = result.get("emotion", "NEUTRAL")
                    text = result.get("text", "").strip()
                    
                    logger.info(f"   🎤 ASR: [{emotion}] \"{text[:50]}...\"")
                    return emotion, text
                else:
                    error = await resp.text()
                    logger.warning(f"   ⚠️ ASR error {resp.status}: {error[:100]}")
                    
        except Exception as e:
            logger.error(f"   ❌ ASR failed: {e}")
            
        return "NEUTRAL", ""
    
    # ===== Brain with Emotional Reasoning =====
    
    async def generate_emotional_response(
        self, 
        session: CallSession, 
        user_text: str,
        user_emotion: str
    ) -> tuple[str, str]:
        """
        Generate response with emotional reasoning.
        
        Returns:
            (emotion, response_text) tuple
        """
        # Build conversation history
        messages = [{"role": "system", "content": session.system_prompt}]
        
        for turn in list(session.history)[-6:]:
            messages.append({
                "role": turn.get("role", "user"),
                "content": turn.get("content", "")
            })
        
        # Add current user message
        messages.append({"role": "user", "content": user_text})
        
        payload = {
            "model": "qwen3.5-9b",
            "messages": messages,
            "max_tokens": 100,
            "temperature": 0.7,
            "user_emotion": user_emotion
        }
        
        try:
            async with self.http_session.post(BRAIN_URL, json=payload) as resp:
                if resp.status == 200:
                    # Get emotion from header
                    response_emotion = resp.headers.get("X-Response-Emotion", "NEUTRAL")
                    result = await resp.json()
                    text = result["choices"][0]["message"]["content"]
                    
                    logger.info(f"   🧠 Brain: <{response_emotion}> \"{text[:50]}...\"")
                    return response_emotion, text
                else:
                    error = await resp.text()
                    logger.error(f"   ❌ Brain error {resp.status}: {error[:100]}")
                    
        except Exception as e:
            logger.error(f"   ❌ Brain failed: {e}")
            
        return "NEUTRAL", "I'm sorry, I didn't catch that."
    
    # ===== TTS with Emotional Voice =====
    
    async def synthesize_emotional(
        self,
        session: CallSession,
        text: str,
        emotion: str
    ):
        """
        Synthesize speech with emotional voice.
        
        Maps brain emotion to TTS voice:
        EMPATHETIC -> empathetic voice
        CHEERFUL -> cheerful voice
        THINKING -> thinking voice
        URGENT -> urgent voice
        NEUTRAL -> neutral voice
        """
        if not session.websocket or not session.stream_sid:
            return
        
        # Map brain emotion to TTS voice
        voice_map = {
            "EMPATHETIC": "empathetic",
            "CHEERFUL": "cheerful",
            "THINKING": "thinking",
            "URGENT": "urgent",
            "PROFESSIONAL": "neutral",
            "NEUTRAL": "neutral"
        }
        voice = voice_map.get(emotion, "neutral")
        
        try:
            payload = {
                "input": text,
                "voice": voice,
                "emotion": voice,
                "response_format": "pcm",
                "speed": 1.0
            }
            
            logger.info(f"   🎙️ TTS: voice={voice}")
            
            async with self.http_session.post(
                TTS_URL,
                json=payload,
                timeout=60
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"   ❌ TTS error {resp.status}: {error[:100]}")
                    return
                
                # Stream audio chunks to Twilio
                chunk_count = 0
                async for pcm_chunk in resp.content.iter_chunked(480):  # 10ms @ 24kHz
                    if pcm_chunk:
                        ulaw = self.audio_processor.resample_24k_to_ulaw(pcm_chunk)
                        
                        await session.websocket.send_json({
                            "event": "media",
                            "streamSid": session.stream_sid,
                            "media": {"payload": base64.b64encode(ulaw).decode()}
                        })
                        chunk_count += 1
                
                logger.info(f"   ✅ Streamed {chunk_count} chunks")
                
        except Exception as e:
            logger.error(f"   ❌ TTS failed: {e}")
    
    # ===== Main Turn Processing =====
    
    async def process_audio_chunk(self, session: CallSession, ulaw_chunk: bytes) -> bool:
        """Process incoming audio chunk."""
        if session.is_processing:
            return False
        
        # Convert and buffer audio
        pcm_8k = self.audio_processor.ulaw_to_pcm(ulaw_chunk)
        pcm_16k = self.audio_processor.resample_8k_to_16k(pcm_8k)
        
        session.audio_buffer.extend(pcm_16k)
        energy = self.audio_processor.calculate_energy(pcm_16k)
        buffer_duration_ms = len(session.audio_buffer) / (TARGET_RATE * 2) * 1000
        
        # Update silence tracking
        if energy < SILENCE_THRESHOLD:
            session.silence_duration_ms += 20
        else:
            session.silence_duration_ms = 0
        
        # Check if we should process
        should_process = (
            (buffer_duration_ms >= MIN_UTTERANCE_MS and session.silence_duration_ms > 300) or
            buffer_duration_ms >= MAX_UTTERANCE_MS
        )
        
        if should_process and len(session.audio_buffer) > 1000:
            audio_to_process = bytes(session.audio_buffer)
            session.audio_buffer = bytearray()
            session.silence_duration_ms = 0
            session.is_processing = True
            
            # Process turn asynchronously
            asyncio.create_task(
                self._process_turn(session, audio_to_process)
            )
            return True
        
        return False
    
    async def _process_turn(self, session: CallSession, pcm_16k: bytes):
        """Process one conversation turn with emotional metadata bridge."""
        try:
            call_id = session.call_sid[:16]
            
            # Step 1: ASR with emotion extraction
            logger.info(f"👂 [{call_id}...] Listening...")
            user_emotion, user_text = await self.transcribe_with_emotion(pcm_16k)
            
            if not user_text:
                session.is_processing = False
                return
            
            session.last_user_emotion = user_emotion
            
            # Step 2: Brain with emotional reasoning
            logger.info(f"   💭 Reasoning...")
            response_emotion, response_text = await self.generate_emotional_response(
                session, user_text, user_emotion
            )
            
            # Step 3: TTS with emotional voice
            await self.synthesize_emotional(session, response_text, response_emotion)
            
            # Update history
            session.history.append({
                "role": "user",
                "content": user_text,
                "emotion": user_emotion
            })
            session.history.append({
                "role": "assistant",
                "content": response_text,
                "emotion": response_emotion
            })
            
            logger.info(f"   ✅ Turn complete")
            
        except Exception as e:
            logger.error(f"   ❌ Turn error: {e}")
        finally:
            session.is_processing = False

# ============== FastAPI Application ==============

orchestrator = EmotionalOrchestrator()
app = FastAPI(title="Emotional Metadata Bridge")

@app.on_event("startup")
async def startup():
    await orchestrator.start()

@app.on_event("shutdown")
async def shutdown():
    await orchestrator.stop()

@app.get("/health")
async def health():
    return {"status": "healthy", "mode": "emotional_bridge"}

@app.post("/twilio/inbound")
async def inbound(CallSid: str = Form(...), From: str = Form(...)):
    """Handle incoming Twilio call."""
    logger.info(f"📞 Call from {From}")
    orchestrator.create_session(CallSid)
    
    stream_url = os.environ.get("STREAM_URL", "wss://localhost:8080/twilio/stream")
    
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}" />
    </Connect>
</Response>"""
    
    return PlainTextResponse(content=twiml, media_type="application/xml")

@app.websocket("/twilio/stream")
async def stream(websocket: WebSocket):
    """Handle WebSocket stream from Twilio."""
    await websocket.accept()
    logger.info("🔌 WebSocket connected")
    
    call_sid = None
    stream_sid = None
    
    try:
        while True:
            message = await websocket.receive_text()
            msg = json.loads(message)
            
            if msg["event"] == "start":
                call_sid = msg["start"]["callSid"]
                stream_sid = msg["start"]["streamSid"]
                session = orchestrator.get_session(call_sid)
                if session:
                    session.stream_sid = stream_sid
                    session.websocket = websocket
                logger.info(f"📞 Call started: {call_sid[:16]}...")
                
            elif msg["event"] == "media":
                if call_sid:
                    session = orchestrator.get_session(call_sid)
                    if session:
                        ulaw_chunk = base64.b64decode(msg["media"]["payload"])
                        await orchestrator.process_audio_chunk(session, ulaw_chunk)
                        
            elif msg["event"] == "stop":
                logger.info(f"📞 Call ended: {call_sid[:16] if call_sid else 'unknown'}...")
                if call_sid:
                    orchestrator.remove_session(call_sid)
                break
                
    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected")
        if call_sid:
            orchestrator.remove_session(call_sid)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        if call_sid:
            orchestrator.remove_session(call_sid)

if __name__ == "__main__":
    import uvicorn
    
    logger.info("╔══════════════════════════════════════════════════════════════╗")
    logger.info("║     Emotional Metadata Bridge - Starting                    ║")
    logger.info("╠══════════════════════════════════════════════════════════════╣")
    logger.info("║  ASR:  http://localhost:8001  [Emotion Extraction]          ║")
    logger.info("║  Brain: http://localhost:8000  [Emotional Reasoning]        ║")
    logger.info("║  TTS:  http://localhost:8002  [Emotional Voice]             ║")
    logger.info("╚══════════════════════════════════════════════════════════════╝")
    
    uvicorn.run(app, host="0.0.0.0", port=8080)
