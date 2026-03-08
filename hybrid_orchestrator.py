#!/usr/bin/env python3
"""
Hybrid Orchestrator: Qwen 3-Omni 30B (Combined Ear+Brain) + MOSS-TTS (Voice)

Architecture:
- Port 8001: Qwen 3-Omni 30B - Handles audio input, emotion detection, and reasoning
- Port 5002: MOSS-TTS llama.cpp - Emotional voice cloning with custom voices

Flow:
User Audio → Qwen 3-Omni (ASR + Emotion + Reasoning) → Text + Emotion → MOSS-TTS → Phil's Voice
"""

import os
import io
import base64
import audioop
import asyncio
import logging
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import PlainTextResponse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============== Configuration ==============

COMBINED_URL = "http://localhost:8001/v1/chat/completions"  # Qwen 3-Omni (ASR + Brain)
VOICE_URL = "http://localhost:5002/v1/audio/speech"         # MOSS-TTS (Voice)

# Audio settings
TARGET_RATE = 16000
SILENCE_THRESHOLD = 0.01
MIN_UTTERANCE_MS = 500
MAX_UTTERANCE_MS = 8000

# Emotion mapping: Omni output emotion → MOSS-TTS voice
EMOTION_VOICE_MAP = {
    "neutral": "neutral",
    "empathetic": "empathetic",
    "sympathetic": "empathetic",
    "caring": "empathetic",
    "cheerful": "cheerful",
    "happy": "cheerful",
    "excited": "cheerful",
    "thinking": "thinking",
    "contemplative": "thinking",
    "urgent": "urgent",
    "frustrated": "urgent",
    "serious": "urgent",
}

# ============== Audio Processing ==============

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

# ============== Hybrid Orchestrator ==============

class HybridOrchestrator:
    """
    Orchestrates Qwen 3-Omni (Combined Ear+Brain) → MOSS-TTS (Voice)
    
    Qwen 3-Omni handles:
    - Audio understanding (ASR)
    - Emotion detection from speech
    - Reasoning and response generation
    
    MOSS-TTS handles:
    - Emotional voice synthesis with custom voice cloning
    """
    
    def __init__(self):
        self.sessions: dict[str, CallSession] = {}
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.audio_processor = AudioProcessor()
        
    async def start(self):
        """Initialize HTTP session."""
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120),
            headers={"Content-Type": "application/json"}
        )
        
        await self._check_services()
        
        logger.info("🚀 Hybrid Orchestrator initialized")
        logger.info("   🧠🎤 Combined: Qwen 3-Omni 30B :8001 (ASR + Brain)")
        logger.info("   🎙️ Voice: MOSS-TTS llama.cpp :5002 (Emotional Voice)")
        
    async def stop(self):
        if self.http_session:
            await self.http_session.close()
            
    async def _check_services(self):
        """Check if all services are running."""
        services = [
            ("Combined (Qwen 3-Omni)", "http://localhost:8001/health"),
            ("Voice (MOSS-TTS)", "http://localhost:5002/health"),
        ]
        
        for name, url in services:
            try:
                async with self.http_session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        logger.info(f"✅ {name} ready")
                    else:
                        logger.warning(f"⚠️ {name} returned {resp.status}")
            except Exception as e:
                logger.error(f"❌ {name} unavailable: {e}")
    
    def create_session(self, call_sid: str) -> CallSession:
        session = CallSession(call_sid=call_sid)
        self.sessions[call_sid] = session
        return session
        
    def get_session(self, call_sid: str) -> Optional[CallSession]:
        return self.sessions.get(call_sid)
        
    def remove_session(self, call_sid: str):
        self.sessions.pop(call_sid, None)
    
    # ===== Qwen 3-Omni: Audio → Text + Emotion =====
    
    async def process_audio_with_omni(self, pcm_16k: bytes) -> tuple[str, str]:
        """
        Send audio to Qwen 3-Omni for ASR + emotion + reasoning.
        
        Returns:
            (response_text, emotion) tuple
        """
        try:
            # Convert PCM to WAV for API
            import wave
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm_16k)
            
            audio_b64 = base64.b64encode(wav_buffer.getvalue()).decode()
            
            # Multimodal payload for Qwen 3-Omni
            # We ask it to detect emotion and respond appropriately
            payload = {
                "model": "/models/Qwen3-Omni-30B-A3B" if os.path.exists("/home/phil/telephony-stack/models/Qwen3-Omni-30B-A3B") else "/models/Qwen2.5-Omni-7B",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are Phil, a helpful AI assistant. Analyze the user's audio for emotion (neutral, empathetic, cheerful, thinking, or urgent) and respond with matching emotional tone. Start your response with [EMOTION: X] where X is the detected emotion."
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": audio_b64,
                                    "format": "wav"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 200,
                "temperature": 0.7
            }
            
            async with self.http_session.post(COMBINED_URL, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    content = result["choices"][0]["message"]["content"]
                    
                    # Parse emotion and text
                    emotion, text = self._parse_emotion_response(content)
                    
                    logger.info(f"   🧠🎤 Omni: [{emotion}] \"{text[:50]}...\"")
                    return text, emotion
                else:
                    error = await resp.text()
                    logger.warning(f"   ⚠️ Omni error {resp.status}: {error[:100]}")
                    
        except Exception as e:
            logger.error(f"   ❌ Omni processing failed: {e}")
            
        return "I'm sorry, I didn't catch that.", "neutral"
    
    def _parse_emotion_response(self, content: str) -> tuple[str, str]:
        """Parse [EMOTION: X] tag from response."""
        content = content.strip()
        
        # Look for emotion tag
        import re
        match = re.search(r'\[EMOTION:\s*(\w+)\]', content, re.IGNORECASE)
        
        if match:
            emotion = match.group(1).lower()
            # Remove the tag from text
            text = re.sub(r'\[EMOTION:\s*\w+\]\s*', '', content, flags=re.IGNORECASE).strip()
        else:
            emotion = "neutral"
            text = content
        
        # Normalize emotion
        emotion = EMOTION_VOICE_MAP.get(emotion, "neutral")
        
        return text, emotion
    
    # ===== MOSS-TTS: Text + Emotion → Audio =====
    
    async def synthesize_emotional(
        self,
        session: CallSession,
        text: str,
        emotion: str
    ):
        """Synthesize speech with emotional voice matching."""
        if not session.websocket or not session.stream_sid:
            return
        
        # Map to MOSS-TTS voice
        voice = EMOTION_VOICE_MAP.get(emotion, "neutral")
        
        try:
            payload = {
                "input": text,
                "voice": voice,
                "emotion": voice,
                "response_format": "pcm",
                "speed": 1.0
            }
            
            logger.info(f"   🎙️ TTS: voice={voice}")
            
            async with self.http_session.post(VOICE_URL, json=payload, timeout=60) as resp:
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
    
    # ===== Main Processing Loop =====
    
    async def process_audio_chunk(self, session: CallSession, ulaw_chunk: bytes) -> bool:
        """Process incoming audio from Twilio."""
        if session.is_processing:
            return False
        
        # Convert μ-law to PCM and resample
        pcm_8k = self.audio_processor.ulaw_to_pcm(ulaw_chunk)
        pcm_16k = self.audio_processor.resample_8k_to_16k(pcm_8k)
        
        session.audio_buffer.extend(pcm_16k)
        energy = self.audio_processor.calculate_energy(pcm_16k)
        buffer_duration_ms = len(session.audio_buffer) / (TARGET_RATE * 2) * 1000
        
        # Track silence
        if energy < SILENCE_THRESHOLD:
            session.silence_duration_ms += 20
        else:
            session.silence_duration_ms = 0
        
        # Check if ready to process
        should_process = (
            (buffer_duration_ms >= MIN_UTTERANCE_MS and session.silence_duration_ms > 300) or
            buffer_duration_ms >= MAX_UTTERANCE_MS
        )
        
        if should_process and len(session.audio_buffer) > 1000:
            audio_to_process = bytes(session.audio_buffer)
            session.audio_buffer = bytearray()
            session.silence_duration_ms = 0
            session.is_processing = True
            
            asyncio.create_task(
                self._process_turn(session, audio_to_process)
            )
            return True
        
        return False
    
    async def _process_turn(self, session: CallSession, pcm_16k: bytes):
        """Process one conversation turn."""
        try:
            call_id = session.call_sid[:16]
            logger.info(f"👂 [{call_id}...] Processing turn")
            
            # Step 1: Qwen 3-Omni - Audio → Text + Emotion
            response_text, emotion = await self.process_audio_with_omni(pcm_16k)
            
            if not response_text:
                session.is_processing = False
                return
            
            # Step 2: MOSS-TTS - Text + Emotion → Voice
            await self.synthesize_emotional(session, response_text, emotion)
            
            # Update history
            session.history.append({
                "role": "assistant",
                "content": response_text,
                "emotion": emotion
            })
            
            logger.info(f"   ✅ Turn complete")
            
        except Exception as e:
            logger.error(f"   ❌ Turn error: {e}")
        finally:
            session.is_processing = False

# ============== FastAPI Application ==============

orchestrator = HybridOrchestrator()
app = FastAPI(title="Hybrid Orchestrator - Qwen 3-Omni + MOSS-TTS")

@app.on_event("startup")
async def startup():
    await orchestrator.start()

@app.on_event("shutdown")
async def shutdown():
    await orchestrator.stop()

@app.get("/health")
async def health():
    return {"status": "healthy", "stack": "hybrid_qwen_omni_moss"}

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
    
    logger.info("╔════════════════════════════════════════════════════════════════╗")
    logger.info("║     🚀 Hybrid Stack Starting                                  ║")
    logger.info("╠════════════════════════════════════════════════════════════════╣")
    logger.info("║  🧠🎤 Combined: Qwen 3-Omni 30B (Port 8001)                   ║")
    logger.info("║  🎙️ Voice: MOSS-TTS llama.cpp (Port 5002)                     ║")
    logger.info("╚════════════════════════════════════════════════════════════════╝")
    
    uvicorn.run(app, host="0.0.0.0", port=8080)
