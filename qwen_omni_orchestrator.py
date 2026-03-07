#!/usr/bin/env python3
"""
Qwen Omni Stack Orchestrator with Emotional Metadata Bridge
Integrates Qwen2.5-Omni (Ear) + Qwen3.5-9B (Brain) + MOSS-TTS (Voice)

Architecture:
- Port 8001: Qwen2.5-Omni - Audio input with emotion extraction
- Port 8000: Qwen3.5-9B - Emotional reasoning and response
- Port 8002: MOSS-TTS-Realtime - Emotional voice synthesis
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
from typing import Optional, List, Dict

import numpy as np
import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import PlainTextResponse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============== Configuration ==============

# Qwen Omni Stack Endpoints
EAR_URL = "http://localhost:8001/v1/chat/completions"    # Qwen2.5-Omni (ASR + Emotion)
BRAIN_URL = "http://localhost:8000/v1/chat/completions"   # Qwen3.5-9B (Reasoning)
VOICE_URL = "http://localhost:8002/v1/audio/speech"       # MOSS-TTS (Voice)

# Audio settings
TARGET_RATE = 16000
SILENCE_THRESHOLD = 0.01
MIN_UTTERANCE_MS = 500
MAX_UTTERANCE_MS = 8000

# Emotion chain mapping
EMOTION_CHAIN = {
    "FRUSTRATED": {"response": "EMPATHETIC", "voice": "empathetic"},
    "JOYFUL": {"response": "CHEERFUL", "voice": "cheerful"},
    "HESITANT": {"response": "THINKING", "voice": "thinking"},
    "URGENT": {"response": "URGENT", "voice": "urgent"},
    "CONFUSED": {"response": "EMPATHETIC", "voice": "empathetic"},
    "NEUTRAL": {"response": "NEUTRAL", "voice": "neutral"},
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
    last_user_emotion: str = "NEUTRAL"

# ============== Qwen Omni Orchestrator ==============

class QwenOmniOrchestrator:
    """
    Orchestrates the Qwen Omni Stack with emotional metadata bridging.
    
    Uses multimodal payloads for Qwen2.5-Omni audio understanding.
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
        
        logger.info("🚀 Qwen Omni Orchestrator initialized")
        logger.info("   🎤 Ear:  Qwen2.5-Omni-7B  :8001 (multimodal audio)")
        logger.info("   🧠 Brain: Qwen3.5-9B-NVFP4 :8000 (emotional reasoning)")
        logger.info("   🎙️ Voice: MOSS-TTS-Realtime :8002 (emotional voice)")
        
    async def stop(self):
        if self.http_session:
            await self.http_session.close()
            
    async def _check_services(self):
        """Check if all services are running."""
        services = [
            ("Ear (Qwen2.5-Omni)", "http://localhost:8001/health"),
            ("Brain (Qwen3.5)", "http://localhost:8000/health"),
            ("Voice (MOSS-TTS)", "http://localhost:8002/health"),
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
    
    # ===== Qwen2.5-Omni Audio Understanding (The Ear) =====
    
    async def transcribe_with_emotion_omni(self, pcm_16k: bytes) -> tuple[str, str]:
        """
        Use Qwen2.5-Omni for audio understanding with emotion detection.
        
        Returns:
            (emotion, transcription) tuple
        """
        try:
            # Convert PCM to WAV
            import wave
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm_16k)
            
            audio_b64 = base64.b64encode(wav_buffer.getvalue()).decode()
            
            # Multimodal payload for Qwen2.5-Omni
            payload = {
                "model": "/models/Qwen2.5-Omni-7B",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Transcribe this audio and identify the speaker's emotion (NEUTRAL, FRUSTRATED, JOYFUL, HESITANT, URGENT, CONFUSED):"
                            },
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
                "max_tokens": 256,
                "temperature": 0.3
            }
            
            async with self.http_session.post(EAR_URL, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    content = result["choices"][0]["message"]["content"]
                    
                    # Parse emotion from response
                    emotion, text = self._parse_omni_response(content)
                    
                    logger.info(f"   🎤 Omni Ear: [{emotion}] \"{text[:50]}...\"")
                    return emotion, text
                else:
                    error = await resp.text()
                    logger.warning(f"   ⚠️ Omni Ear error {resp.status}: {error[:100]}")
                    
        except Exception as e:
            logger.error(f"   ❌ Omni Ear failed: {e}")
            
        return "NEUTRAL", ""
    
    def _parse_omni_response(self, content: str) -> tuple[str, str]:
        """Parse emotion from Qwen2.5-Omni response."""
        content = content.strip()
        
        # Look for emotion tags
        emotions = ["FRUSTRATED", "JOYFUL", "HESITANT", "URGENT", "CONFUSED", "NEUTRAL"]
        detected_emotion = "NEUTRAL"
        
        for emotion in emotions:
            if f"[{emotion}]" in content.upper() or emotion.upper() in content.upper()[:50]:
                detected_emotion = emotion
                break
        
        # Extract transcription (remove emotion labels)
        text = content
        for emotion in emotions:
            text = text.replace(f"[{emotion}]", "").replace(f"{emotion}:", "")
        
        text = text.strip().strip('"').strip("'")
        
        return detected_emotion, text
    
    # ===== Qwen3.5-9B Emotional Reasoning (The Brain) =====
    
    async def generate_emotional_response(
        self, 
        session: CallSession, 
        user_text: str,
        user_emotion: str
    ) -> tuple[str, str]:
        """
        Generate emotionally appropriate response using Qwen3.5-9B.
        """
        # Build conversation history
        messages = []
        
        # System prompt with emotional context
        system_prompt = f"""You are Phil, a helpful and empathetic AI assistant. 
The user is feeling {user_emotion}. Respond with appropriate emotional intelligence.
Start your response with an emotion tag: <EMPATHETIC>, <CHEERFUL>, <THINKING>, <URGENT>, or <NEUTRAL>."""
        
        messages.append({"role": "system", "content": system_prompt})
        
        # Add history
        for turn in list(session.history)[-4:]:
            messages.append({
                "role": turn.get("role", "user"),
                "content": turn.get("content", "")
            })
        
        # Add current user message with emotion context
        messages.append({
            "role": "user", 
            "content": f"[{user_emotion}] {user_text}"
        })
        
        payload = {
            "model": "/models/quantized/Qwen3.5-9B-NVFP4",
            "messages": messages,
            "max_tokens": 150,
            "temperature": 0.7
        }
        
        try:
            async with self.http_session.post(BRAIN_URL, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    content = result["choices"][0]["message"]["content"]
                    
                    # Parse emotion tag from response
                    emotion, text = self._parse_brain_response(content)
                    
                    logger.info(f"   🧠 Brain: <{emotion}> \"{text[:50]}...\"")
                    return emotion, text
                else:
                    error = await resp.text()
                    logger.error(f"   ❌ Brain error {resp.status}: {error[:100]}")
                    
        except Exception as e:
            logger.error(f"   ❌ Brain failed: {e}")
            
        return "NEUTRAL", "I'm sorry, I didn't catch that."
    
    def _parse_brain_response(self, content: str) -> tuple[str, str]:
        """Parse emotion tag from Brain response."""
        content = content.strip()
        
        emotions = ["EMPATHETIC", "CHEERFUL", "THINKING", "URGENT", "NEUTRAL"]
        
        for emotion in emotions:
            tag = f"<{emotion}>"
            if tag in content.upper():
                parts = content.split(tag, 1)
                if len(parts) > 1:
                    return emotion, parts[1].strip().strip('"')
                return emotion, ""
        
        return "NEUTRAL", content
    
    # ===== MOSS-TTS Emotional Voice (The Voice) =====
    
    async def synthesize_emotional(
        self,
        session: CallSession,
        text: str,
        emotion: str
    ):
        """Synthesize speech with emotional voice matching."""
        if not session.websocket or not session.stream_sid:
            return
        
        # Map brain emotion to TTS voice
        voice_map = {
            "EMPATHETIC": "empathetic",
            "CHEERFUL": "cheerful",
            "THINKING": "thinking",
            "URGENT": "urgent",
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
            
            logger.info(f"   🎙️ Voice: {voice}")
            
            async with self.http_session.post(VOICE_URL, json=payload, timeout=60) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"   ❌ Voice error {resp.status}: {error[:100]}")
                    return
                
                # Stream audio chunks
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
            logger.error(f"   ❌ Voice failed: {e}")
    
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
            
            # Step 1: Qwen2.5-Omni - Audio understanding with emotion
            user_emotion, user_text = await self.transcribe_with_emotion_omni(pcm_16k)
            
            if not user_text:
                session.is_processing = False
                return
            
            session.last_user_emotion = user_emotion
            
            # Step 2: Qwen3.5-9B - Emotional reasoning
            response_emotion, response_text = await self.generate_emotional_response(
                session, user_text, user_emotion
            )
            
            # Step 3: MOSS-TTS - Emotional voice synthesis
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

orchestrator = QwenOmniOrchestrator()
app = FastAPI(title="Qwen Omni Stack Orchestrator")

@app.on_event("startup")
async def startup():
    await orchestrator.start()

@app.on_event("shutdown")
async def shutdown():
    await orchestrator.stop()

@app.get("/health")
async def health():
    return {"status": "healthy", "stack": "qwen_omni"}

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
    logger.info("║     🚀 Qwen Omni Stack - Starting                             ║")
    logger.info("╠════════════════════════════════════════════════════════════════╣")
    logger.info("║  🎤 Ear:   Qwen2.5-Omni-7B  :8001 (Multimodal Audio)          ║")
    logger.info("║  🧠 Brain: Qwen3.5-9B-NVFP4 :8000 (Emotional Reasoning)       ║")
    logger.info("║  🎙️ Voice:  MOSS-TTS-Realtime :8002 (Zero-Shot Cloning)        ║")
    logger.info("╚════════════════════════════════════════════════════════════════╝")
    
    uvicorn.run(app, host="0.0.0.0", port=8080)
