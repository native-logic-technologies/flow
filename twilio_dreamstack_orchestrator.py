#!/usr/bin/env python3
"""
Dream Stack Twilio Orchestrator with Barge-In Support
- Handles 8kHz μ-law audio from Twilio
- Real-time transcription with Llama-Omni
- Emotional response generation with Nemotron
- Streaming TTS with MOSS-TTS
- BARGE-IN: Caller can interrupt at any time
"""

import os
import io
import base64
import audioop
import asyncio
import logging
import json
import re
import time
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Tuple

import numpy as np
import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import PlainTextResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== Configuration ==============

BRAIN_URL = "http://localhost:8000/v1/chat/completions"
VOICE_URL = "http://localhost:8002/v1/audio/speech"
EAR_URL = "http://localhost:8001/v1/chat/completions"

# Audio settings for Twilio
TWILIO_RATE = 8000        # Twilio sends 8kHz
TARGET_RATE = 16000       # Ear expects 16kHz
MOSS_RATE = 24000         # MOSS-TTS outputs 24kHz

# VAD / Barge-in settings
SILENCE_THRESHOLD = 0.015  # Energy threshold for speech detection
MIN_UTTERANCE_MS = 400     # Minimum speech to process
MAX_UTTERANCE_MS = 10000   # Maximum utterance length
BARGE_IN_THRESHOLD = 0.02  # Energy threshold for barge-in detection

# Emotion mapping
EMOTION_MAP = {
    "excited": "excited",
    "happy": "happy",
    "cheerful": "happy",
    "neutral": "neutral",
    "calm": "calm",
    "sad": "sad",
    "empathetic": "empathetic",
    "sympathetic": "empathetic",
    "caring": "empathetic",
    "serious": "serious",
    "urgent": "urgent",
    "thinking": "thinking",
}

# ============== Audio Processing ==============

class AudioProcessor:
    """Handle 8kHz μ-law (Twilio) ↔ 16kHz PCM (Ear) ↔ 24kHz PCM (MOSS-TTS)"""
    
    @staticmethod
    def ulaw_to_pcm(ulaw_data: bytes) -> bytes:
        """Convert μ-law to 16-bit PCM"""
        return audioop.ulaw2lin(ulaw_data, 2)
    
    @staticmethod
    def pcm_to_ulaw(pcm_data: bytes) -> bytes:
        """Convert 16-bit PCM to μ-law"""
        return audioop.lin2ulaw(pcm_data, 2)
    
    @staticmethod
    def resample_8k_to_16k(pcm_8k: bytes) -> bytes:
        """Resample 8kHz PCM to 16kHz for Ear"""
        return audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)[0]
    
    @staticmethod
    def resample_16k_to_8k(pcm_16k: bytes) -> bytes:
        """Resample 16kHz PCM to 8kHz for output"""
        return audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)[0]
    
    @staticmethod
    def resample_24k_to_8k_ulaw(pcm_24k: bytes) -> bytes:
        """Resample 24kHz (MOSS-TTS) to 8kHz μ-law (Twilio)"""
        # 24kHz → 16kHz → 8kHz → μ-law
        pcm_16k = audioop.ratecv(pcm_24k, 2, 1, 24000, 16000, None)[0]
        pcm_8k = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)[0]
        return audioop.lin2ulaw(pcm_8k, 2)
    
    @staticmethod
    def calculate_energy(pcm_bytes: bytes) -> float:
        """Calculate audio energy for VAD"""
        if len(pcm_bytes) < 2:
            return 0.0
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return np.abs(audio).mean()

# ============== Emotional Prosody Parser ==============

@dataclass
class EmotionalSentence:
    emotion: str
    text: str
    index: int = 0

class EmotionalProsodyParser:
    """Parse [EMOTION: X] tagged responses"""
    
    @classmethod
    def parse(cls, text: str) -> List[EmotionalSentence]:
        if not text or not text.strip():
            return []
        
        # Handle both [EMOTION: X] and [X] formats
        # Try [EMOTION: X] format first
        pattern = r'\[EMOTION:\s*(\w+)\]\s*([^\[]+?)(?=\[EMOTION:|\[\w+\]:?$|$)'
        matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
        
        # If no matches, try [X] format (e.g., [NEUTRAL] text)
        if not matches:
            pattern = r'\[(\w+)\]\s*([^.!?]*[.!?])'
            matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
        
        sentences = []
        for i, (emotion, text_part) in enumerate(matches):
            emotion = emotion.lower().strip()
            normalized = EMOTION_MAP.get(emotion, "neutral")
            
            # Split into sentences
            sub_sentences = re.split(r'(?<=[.!?])\s+', text_part.strip())
            for sub in sub_sentences:
                if sub.strip():
                    sentences.append(EmotionalSentence(
                        emotion=normalized,
                        text=sub.strip(),
                        index=len(sentences)
                    ))
        
        # Fallback if no emotion tags
        if not sentences and text.strip():
            clean = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
            clean = re.sub(r'</think>', '', clean).strip()
            if clean:
                sentences.append(EmotionalSentence("neutral", clean, 0))
        
        return sentences

# ============== Call Session ==============

@dataclass
class CallSession:
    """Active call state with barge-in support"""
    call_sid: str
    stream_sid: Optional[str] = None
    websocket: Optional[WebSocket] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    # Audio buffers
    audio_buffer: bytearray = field(default_factory=bytearray)
    
    # State
    is_processing: bool = False
    is_speaking: bool = False  # True when AI is speaking (for barge-in)
    silence_duration_ms: float = 0.0
    
    # Barge-in
    last_caller_energy: float = 0.0
    barge_in_triggered: bool = False
    
    # Metrics
    turn_count: int = 0
    latencies: List[float] = field(default_factory=list)
    
    # Current TTS task (for cancellation)
    current_tts_task: Optional[asyncio.Task] = None

# ============== Twilio Dream Stack Orchestrator ==============

class TwilioDreamStackOrchestrator:
    """
    Full Dream Stack with Twilio integration:
    - 8kHz μ-law audio from Twilio
    - Real-time ASR with Llama-Omni (simulated via text for now)
    - Emotional LLM with Nemotron
    - Streaming TTS with MOSS-TTS
    - BARGE-IN: Caller can interrupt AI speech
    """
    
    def __init__(self):
        self.sessions: dict[str, CallSession] = {}
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.audio_processor = AudioProcessor()
        
    async def start(self):
        """Initialize HTTP session"""
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
            headers={"Content-Type": "application/json"}
        )
        
        await self._check_services()
        
        logger.info("🚀 Twilio Dream Stack Orchestrator initialized")
        logger.info("   📞 Port: 8080 (Twilio WebSocket)")
        logger.info("   🎯 Features: Barge-in, 8kHz→16kHz, Emotional Prosody")
        
    async def stop(self):
        if self.http_session:
            await self.http_session.close()
    
    async def _check_services(self):
        """Verify all backend services"""
        services = [
            ("Brain (Nemotron)", "http://localhost:8000/health"),
            ("Ear (Llama-Omni)", "http://localhost:8001/health"),
            ("Voice (MOSS-TTS)", "http://localhost:8002/health"),
        ]
        
        for name, url in services:
            try:
                async with self.http_session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        logger.info(f"   ✅ {name} ready")
                    else:
                        logger.warning(f"   ⚠️ {name} status {resp.status}")
            except Exception as e:
                logger.error(f"   ❌ {name} unavailable: {e}")
    
    def create_session(self, call_sid: str) -> CallSession:
        session = CallSession(call_sid=call_sid)
        self.sessions[call_sid] = session
        return session
    
    def get_session(self, call_sid: str) -> Optional[CallSession]:
        return self.sessions.get(call_sid)
    
    def remove_session(self, call_sid: str):
        self.sessions.pop(call_sid, None)
    
    # ===== Barge-In Detection =====
    
    def check_barge_in(self, session: CallSession, ulaw_chunk: bytes) -> bool:
        """
        Detect if caller is trying to interrupt (barge-in).
        Returns True if barge-in detected.
        """
        # Convert to PCM and check energy
        pcm_8k = self.audio_processor.ulaw_to_pcm(ulaw_chunk)
        energy = self.audio_processor.calculate_energy(pcm_8k)
        session.last_caller_energy = energy
        
        # Barge-in conditions:
        # 1. AI is currently speaking
        # 2. Caller energy is high (they're speaking loudly)
        # 3. Energy exceeds threshold
        if session.is_speaking and energy > BARGE_IN_THRESHOLD:
            logger.info(f"👂 [{session.call_sid[:12]}...] BARGE-IN detected! (energy: {energy:.3f})")
            session.barge_in_triggered = True
            return True
        
        return False
    
    async def cancel_current_speech(self, session: CallSession):
        """Cancel ongoing TTS when barge-in detected"""
        if session.current_tts_task and not session.current_tts_task.done():
            logger.info(f"🔇 [{session.call_sid[:12]}...] Cancelling AI speech")
            session.current_tts_task.cancel()
            try:
                await session.current_tts_task
            except asyncio.CancelledError:
                pass
            session.current_tts_task = None
        
        session.is_speaking = False
        session.barge_in_triggered = False
    
    # ===== LLM Generation =====
    
    async def generate_response(
        self, 
        user_text: str,
        session: CallSession
    ) -> Tuple[List[EmotionalSentence], float]:
        """Generate emotional response from Nemotron"""
        
        # Nemotron thinking control: use chat_template_kwargs to disable thinking
        system_prompt = "You are a friendly AI voice assistant having a natural phone conversation. Keep responses brief (1-2 sentences). Start with [EMOTION: X] where X is: NEUTRAL, HAPPY, EXCITED, CALM, EMPATHETIC, SERIOUS, or THINKING."

        start_time = time.time()
        
        payload = {
            "model": "models/llm/nemotron-3-nano-30b-nvfp4",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            "max_tokens": 80,
            "temperature": 0.7,
            "stream": False,
            "chat_template_kwargs": {
                "enable_thinking": False
            }
        }
        
        try:
            async with self.http_session.post(BRAIN_URL, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    raw_text = result["choices"][0]["message"]["content"]
                    gen_time = (time.time() - start_time) * 1000
                    
                    # Parse emotional sentences
                    sentences = EmotionalProsodyParser.parse(raw_text)
                    
                    return sentences, gen_time
                else:
                    error = await resp.text()
                    logger.error(f"Brain error: {resp.status} - {error[:100]}")
        except Exception as e:
            logger.error(f"Brain request failed: {e}")
        
        return [EmotionalSentence("neutral", "I'm sorry, I didn't catch that.", 0)], 0.0
    
    # ===== TTS with Barge-In Support =====
    
    async def stream_tts_with_barge_in(
        self,
        session: CallSession,
        sentence: EmotionalSentence
    ) -> bool:
        """
        Stream TTS audio with barge-in detection.
        Returns True if completed, False if barge-in interrupted.
        """
        text_with_emotion = f"[EMOTION: {sentence.emotion.upper()}] {sentence.text}"
        
        # Map emotion to temperature
        temps = {"excited": 0.9, "happy": 0.8, "neutral": 0.7, "calm": 0.6, 
                 "empathetic": 0.7, "serious": 0.5, "thinking": 0.6}
        temperature = temps.get(sentence.emotion, 0.7)
        
        payload = {
            "input": text_with_emotion,
            "voice": "phil",
            "response_format": "pcm",
            "temperature": temperature,
            "top_p": 0.6
        }
        
        try:
            async with self.http_session.post(VOICE_URL, json=payload, timeout=30) as resp:
                if resp.status != 200:
                    logger.error(f"TTS error: {resp.status}")
                    return False
                
                # Stream audio chunks
                chunk_count = 0
                async for pcm_chunk in resp.content.iter_chunked(480):  # 10ms @ 24kHz
                    # Check if barge-in was triggered
                    if session.barge_in_triggered:
                        logger.info(f"🔇 [{session.call_sid[:12]}...] TTS interrupted by barge-in")
                        return False
                    
                    if pcm_chunk and session.websocket and session.stream_sid:
                        # Convert 24kHz PCM to 8kHz μ-law for Twilio
                        ulaw = self.audio_processor.resample_24k_to_8k_ulaw(pcm_chunk)
                        
                        await session.websocket.send_json({
                            "event": "media",
                            "streamSid": session.stream_sid,
                            "media": {"payload": base64.b64encode(ulaw).decode()}
                        })
                        chunk_count += 1
                
                logger.debug(f"Streamed {chunk_count} chunks for sentence")
                return True
                
        except asyncio.CancelledError:
            logger.info(f"🔇 [{session.call_sid[:12]}...] TTS cancelled")
            return False
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return False
    
    # ===== Main Processing Loop =====
    
    async def process_audio_chunk(self, session: CallSession, ulaw_chunk: bytes) -> bool:
        """
        Process incoming audio from Twilio with barge-in support.
        """
        # Check for barge-in first
        if session.is_speaking:
            if self.check_barge_in(session, ulaw_chunk):
                await self.cancel_current_speech(session)
                # Clear buffer and start fresh
                session.audio_buffer = bytearray()
                session.silence_duration_ms = 0
                return True
            # If AI is speaking and no barge-in, ignore caller audio
            return False
        
        # Don't process if already processing
        if session.is_processing:
            return False
        
        # Convert μ-law → PCM → 16kHz
        pcm_8k = self.audio_processor.ulaw_to_pcm(ulaw_chunk)
        pcm_16k = self.audio_processor.resample_8k_to_16k(pcm_8k)
        
        # Add to buffer
        session.audio_buffer.extend(pcm_16k)
        
        # Calculate energy for VAD
        energy = self.audio_processor.calculate_energy(pcm_16k)
        buffer_duration_ms = len(session.audio_buffer) / (TARGET_RATE * 2) * 1000
        
        # Track silence
        if energy < SILENCE_THRESHOLD:
            session.silence_duration_ms += 20  # 20ms per chunk
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
            
            # Process in background
            session.current_tts_task = asyncio.create_task(
                self._process_turn(session, audio_to_process)
            )
            return True
        
        return False
    
    async def _process_turn(self, session: CallSession, pcm_16k: bytes):
        """Process one conversation turn"""
        try:
            call_id = session.call_sid[:12]
            turn_start = time.time()
            session.turn_count += 1
            
            logger.info(f"👂 [{call_id}...] Turn {session.turn_count} started")
            
            # NOTE: For now, we're simulating ASR. In production, send pcm_16k to Llama-Omni
            # For testing, we'll use placeholder transcription
            # TODO: Integrate real ASR with Llama-Omni
            
            # Simulate ASR with a simple prompt-based approach for now
            # In production, this would be: user_text = await self.transcribe_with_ear(pcm_16k)
            user_text = await self._simulate_asr_from_context(session)
            
            if not user_text:
                session.is_processing = False
                return
            
            logger.info(f"📝 [{call_id}...] User: \"{user_text}\"")
            
            # Generate emotional response
            sentences, gen_time = await self.generate_response(user_text, session)
            
            if not sentences:
                session.is_processing = False
                return
            
            logger.info(f"🧠 [{call_id}...] Brain ({gen_time:.0f}ms): {len(sentences)} sentence(s)")
            for sent in sentences:
                logger.info(f"   [{sent.index}] [{sent.emotion.upper()}] \"{sent.text}\"")
            
            # Stream TTS with barge-in support
            session.is_speaking = True
            first_audio_sent = False
            
            for sentence in sentences:
                # Check if barge-in already triggered
                if session.barge_in_triggered:
                    logger.info(f"🔇 [{call_id}...] Skipping remaining sentences due to barge-in")
                    break
                
                # Stream this sentence
                completed = await self.stream_tts_with_barge_in(session, sentence)
                
                if not completed:
                    # Barge-in interrupted
                    break
                
                if not first_audio_sent:
                    first_audio_time = (time.time() - turn_start) * 1000
                    session.latencies.append(first_audio_time)
                    logger.info(f"⏱️  [{call_id}...] First audio: {first_audio_time:.0f}ms")
                    first_audio_sent = True
            
            session.is_speaking = False
            turn_duration = (time.time() - turn_start) * 1000
            logger.info(f"✅ [{call_id}...] Turn {session.turn_count} complete ({turn_duration:.0f}ms)")
            
        except Exception as e:
            logger.error(f"❌ Turn error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            session.is_processing = False
            session.current_tts_task = None
    
    async def _simulate_asr_from_context(self, session: CallSession) -> str:
        """
        Simulate ASR for testing.
        In production, send audio to Llama-Omni Ear.
        """
        # For testing, return placeholder based on turn count
        test_inputs = [
            "Hello, how are you today?",
            "What's the weather like?",
            "Tell me something interesting.",
            "Thank you for the conversation!",
        ]
        
        idx = (session.turn_count - 1) % len(test_inputs)
        return test_inputs[idx]

# ============== FastAPI Application ==============

orchestrator = TwilioDreamStackOrchestrator()
app = FastAPI(title="Dream Stack Twilio Orchestrator with Barge-In")

@app.on_event("startup")
async def startup():
    await orchestrator.start()

@app.on_event("shutdown")
async def shutdown():
    await orchestrator.stop()

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "stack": "dream_stack_twilio",
        "features": ["barge_in", "8khz_ulaw", "emotional_prosody"]
    }

@app.get("/metrics")
async def metrics():
    """Return call metrics"""
    total_calls = len(orchestrator.sessions)
    all_latencies = []
    for session in orchestrator.sessions.values():
        all_latencies.extend(session.latencies)
    
    avg_latency = statistics.mean(all_latencies) if all_latencies else 0
    
    return {
        "active_calls": total_calls,
        "avg_latency_ms": round(avg_latency, 1),
        "total_turns": sum(s.turn_count for s in orchestrator.sessions.values()),
    }

@app.post("/twilio/inbound")
async def inbound(CallSid: str = Form(...), From: str = Form(...)):
    """Handle incoming Twilio call"""
    logger.info(f"📞 Incoming call from {From}")
    orchestrator.create_session(CallSid)
    
    # Get public URL from environment or use Cloudflare default
    public_url = os.environ.get("PUBLIC_URL", "wss://cleans2s.voiceflow.cloud")
    
    # Return TwiML to connect to WebSocket stream
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{public_url}/twilio/stream" />
    </Connect>
</Response>"""
    
    return PlainTextResponse(content=twiml, media_type="application/xml")

@app.websocket("/twilio/stream")
async def stream(websocket: WebSocket):
    """Handle WebSocket stream from Twilio with barge-in support"""
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
                logger.info(f"📞 Call started: {call_sid[:12]}...")
                
            elif msg["event"] == "media":
                if call_sid:
                    session = orchestrator.get_session(call_sid)
                    if session:
                        # Decode μ-law audio from Twilio
                        ulaw_chunk = base64.b64decode(msg["media"]["payload"])
                        await orchestrator.process_audio_chunk(session, ulaw_chunk)
                        
            elif msg["event"] == "stop":
                logger.info(f"📞 Call ended: {call_sid[:12] if call_sid else 'unknown'}...")
                if call_sid:
                    session = orchestrator.get_session(call_sid)
                    if session:
                        avg_latency = statistics.mean(session.latencies) if session.latencies else 0
                        logger.info(f"📊 Call stats: {session.turn_count} turns, {avg_latency:.0f}ms avg latency")
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
    logger.info("║     🚀 Dream Stack Twilio Server                              ║")
    logger.info("╠════════════════════════════════════════════════════════════════╣")
    logger.info("║  📞 Port: 8080 (Twilio WebSocket)                             ║")
    logger.info("║  🎯 Features:                                                  ║")
    logger.info("║     • Barge-in support (caller can interrupt)                 ║")
    logger.info("║     • 8kHz μ-law audio handling                               ║")
    logger.info("║     • Real-time emotional prosody                             ║")
    logger.info("╚════════════════════════════════════════════════════════════════╝")
    
    uvicorn.run(app, host="0.0.0.0", port=8080)
