#!/usr/bin/env python3
"""
Streaming S2S Telephony Server for Twilio
Real-time pipeline: ASR → LLM (streaming) → TTS (streaming) → Twilio

Latency target: <500ms from speech end to audio start
"""

import os
os.environ['HF_HOME'] = '/tmp/hf_cache'

import asyncio
import audioop
import base64
import io
import json
import re
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncGenerator, Dict, Optional, Set

import aiohttp
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import PlainTextResponse
import websockets

# ============== Configuration ==============

BRAIN_URL = "http://localhost:8000/v1/chat/completions"
EAR_URL = "http://localhost:8001/v1/chat/completions"
VOICE_HTTP_URL = "http://localhost:8002/v1/audio/speech"
VOICE_WS_URL = "ws://localhost:8002/ws/tts"

TWILIO_RATE = 8000
TARGET_RATE = 16000
BYTES_PER_SAMPLE = 2
SILENCE_THRESHOLD = 0.01
MIN_UTTERANCE_MS = 500
MAX_UTTERANCE_MS = 8000
CHUNK_DURATION_MS = 20

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
    def calculate_energy(pcm_bytes: bytes) -> float:
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return np.abs(audio).mean()


# ============== Sentence Splitter ==============

class SentenceSplitter:
    """Split text into sentences for streaming TTS."""
    
    SENTENCE_ENDINGS = re.compile(r'([.!?。！？]+\s*)')
    
    @classmethod
    def split(cls, text: str) -> tuple[str, str]:
        """
        Split text into (complete_sentences, remaining_buffer).
        Returns complete sentences and leftover text.
        """
        matches = list(cls.SENTENCE_ENDINGS.finditer(text))
        if not matches:
            return "", text
        
        # Find the last sentence ending
        last_match = matches[-1]
        split_pos = last_match.end()
        
        complete = text[:split_pos].strip()
        remaining = text[split_pos:].strip()
        
        return complete, remaining


# ============== Call Session ==============

@dataclass
class CallSession:
    """State for a single call with streaming support."""
    call_sid: str
    stream_sid: Optional[str] = None
    websocket: Optional[WebSocket] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    # Conversation
    history: deque = field(default_factory=lambda: deque(maxlen=10))
    system_prompt: str = """You are Phil, a helpful AI assistant on a phone call. Be warm, conversational, and concise. Keep responses brief for phone conversations."""
    
    # Audio buffering
    audio_buffer: bytearray = field(default_factory=bytearray)
    silence_duration_ms: float = 0.0
    is_processing: bool = False
    
    # Streaming state
    current_llm_buffer: str = ""  # Buffer for incomplete sentences
    is_speaking: bool = False
    
    # Stats
    total_turns: int = 0
    total_latency_ms: float = 0.0
    
    def add_to_history(self, role: str, text: str):
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "text": text
        })


# ============== Streaming Orchestrator ==============

class StreamingOrchestrator:
    """Real-time streaming orchestrator."""
    
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
        print("🚀 Streaming Orchestrator initialized")
        
    async def stop(self):
        """Cleanup."""
        if self.http_session:
            await self.http_session.close()
            
    def create_session(self, call_sid: str) -> CallSession:
        """Create new call session."""
        session = CallSession(call_sid=call_sid)
        self.sessions[call_sid] = session
        return session
        
    def get_session(self, call_sid: str) -> Optional[CallSession]:
        return self.sessions.get(call_sid)
        
    def remove_session(self, call_sid: str):
        self.sessions.pop(call_sid, None)
    
    # ============ ASR (Ear) ============
    
    async def transcribe_audio(self, pcm_16k: bytes) -> Optional[str]:
        """Transcribe audio using Ear (Qwen2.5-Omni)."""
        try:
            # Create WAV
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(TARGET_RATE)
                wav.writeframes(pcm_16k)
            
            audio_b64 = base64.b64encode(wav_buffer.getvalue()).decode()
            
            payload = {
                "model": "Qwen/Qwen2.5-Omni-7B",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe this audio:"},
                        {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}}
                    ]
                }],
                "max_tokens": 100,
                "temperature": 0.0
            }
            
            async with self.http_session.post(EAR_URL, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result['choices'][0]['message']['content']
        except Exception as e:
            print(f"   ❌ ASR error: {e}")
        return None
    
    # ============ LLM (Brain) - Streaming ============
    
    async def generate_response_stream(
        self, 
        session: CallSession, 
        user_text: str
    ) -> AsyncGenerator[str, None]:
        """
        Stream LLM tokens from Brain.
        Yields text chunks as they arrive.
        """
        # Build messages
        messages = [{"role": "system", "content": session.system_prompt}]
        for turn in list(session.history)[-6:]:
            messages.append({"role": turn["role"], "content": turn["text"]})
        messages.append({"role": "user", "content": user_text})
        
        payload = {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "messages": messages,
            "max_tokens": 80,
            "temperature": 0.7,
            "stream": True  # CRITICAL: Enable streaming
        }
        
        try:
            async with self.http_session.post(BRAIN_URL, json=payload) as resp:
                if resp.status != 200:
                    print(f"   ❌ LLM error: {resp.status}")
                    return
                
                # Stream tokens
                buffer = ""
                async for line in resp.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            if buffer:
                                yield buffer
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk['choices'][0].get('delta', {}).get('content', '')
                            if delta:
                                buffer += delta
                                # Yield every few characters for smooth streaming
                                if len(buffer) >= 3:
                                    yield buffer
                                    buffer = ""
                        except:
                            pass
                
                # Yield any remaining
                if buffer:
                    yield buffer
                    
        except Exception as e:
            print(f"   ❌ LLM stream error: {e}")
    
    # ============ TTS (Voice) - Streaming via WebSocket ============
    
    async def stream_tts_to_twilio(
        self,
        session: CallSession,
        text_stream: AsyncGenerator[str, None]
    ):
        """
        Stream TTS audio to Twilio in real-time.
        Uses WebSocket connection to MOSS-TTS for <500ms latency.
        """
        if not session.websocket or not session.stream_sid:
            return
        
        try:
            # Connect to TTS WebSocket
            async with websockets.connect(VOICE_WS_URL) as tts_ws:
                # Initialize with Phil's voice
                await tts_ws.send(json.dumps({
                    "type": "init",
                    "voice": "phil"
                }))
                
                # Buffer for sentence accumulation
                sentence_buffer = ""
                
                # Process text stream
                async for text_chunk in text_stream:
                    sentence_buffer += text_chunk
                    
                    # Check for complete sentences
                    complete, remaining = SentenceSplitter.split(sentence_buffer)
                    
                    if complete:
                        # Send complete sentence to TTS
                        await tts_ws.send(json.dumps({
                            "type": "text",
                            "text": complete
                        }))
                        sentence_buffer = remaining
                        
                        # Receive audio chunks and forward to Twilio
                        try:
                            while True:
                                # Non-blocking receive with timeout
                                audio_data = await asyncio.wait_for(
                                    tts_ws.recv(),
                                    timeout=0.05
                                )
                                
                                if isinstance(audio_data, bytes):
                                    # Convert PCM to μ-law and send to Twilio
                                    ulaw = self._pcm_to_ulaw(audio_data)
                                    await session.websocket.send_json({
                                        "event": "media",
                                        "streamSid": session.stream_sid,
                                        "media": {"payload": base64.b64encode(ulaw).decode()}
                                    })
                                elif isinstance(audio_data, str):
                                    # Control message
                                    msg = json.loads(audio_data)
                                    if msg.get("type") == "chunk":
                                        continue
                                    elif msg.get("type") == "done":
                                        break
                        except asyncio.TimeoutError:
                            # No more audio for now, continue with next text
                            pass
                
                # Flush remaining text
                if sentence_buffer:
                    await tts_ws.send(json.dumps({
                        "type": "text",
                        "text": sentence_buffer
                    }))
                    await tts_ws.send(json.dumps({"type": "end"}))
                    
                    # Receive remaining audio
                    try:
                        while True:
                            audio_data = await asyncio.wait_for(tts_ws.recv(), timeout=2.0)
                            if isinstance(audio_data, bytes):
                                ulaw = self._pcm_to_ulaw(audio_data)
                                await session.websocket.send_json({
                                    "event": "media",
                                    "streamSid": session.stream_sid,
                                    "media": {"payload": base64.b64encode(ulaw).decode()}
                                })
                    except asyncio.TimeoutError:
                        pass
                        
        except Exception as e:
            print(f"   ❌ TTS stream error: {e}")
    
    def _pcm_to_ulaw(self, pcm_data: bytes) -> bytes:
        """Convert PCM bytes to μ-law."""
        return audioop.lin2ulaw(pcm_data, 2)
    
    # ============ Audio Processing ============
    
    async def process_audio_chunk(
        self, 
        session: CallSession, 
        ulaw_chunk: bytes
    ) -> bool:
        """
        Process incoming audio from Twilio.
        Returns True if utterance complete and processing started.
        """
        if session.is_processing:
            return False
        
        # Convert μ-law → PCM 8k → PCM 16k
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
        
        if should_process and len(session.audio_buffer) > 1000:
            audio_to_process = bytes(session.audio_buffer)
            session.audio_buffer = bytearray()
            session.silence_duration_ms = 0
            session.is_processing = True
            
            # Process in background
            asyncio.create_task(
                self._process_utterance_streaming(session, audio_to_process)
            )
            return True
        
        return False
    
    async def _process_utterance_streaming(
        self, 
        session: CallSession, 
        pcm_16k: bytes
    ):
        """
        Full streaming pipeline: ASR → LLM (stream) → TTS (stream).
        """
        start_time = datetime.now()
        
        try:
            # === STEP 1: ASR ===
            print(f"👂 [{session.call_sid[:16]}...] Transcribing...")
            transcription = await self.transcribe_audio(pcm_16k)
            
            if not transcription:
                session.is_processing = False
                return
            
            print(f"   📝 '{transcription[:60]}...'")
            session.add_to_history("user", transcription)
            
            # === STEP 2 & 3: Streaming LLM → TTS → Twilio ===
            print(f"   💬 Streaming response...")
            
            # Create LLM text stream
            llm_stream = self.generate_response_stream(session, transcription)
            
            # Stream through TTS to Twilio
            await self.stream_tts_to_twilio(session, llm_stream)
            
            # Update stats
            latency = (datetime.now() - start_time).total_seconds() * 1000
            session.total_latency_ms += latency
            session.total_turns += 1
            
            print(f"   ✅ Turn complete (avg latency: {session.total_latency_ms/session.total_turns:.0f}ms)")
            
        except Exception as e:
            print(f"   ❌ Processing error: {e}")
        finally:
            session.is_processing = False


# ============== FastAPI App ==============

orchestrator = StreamingOrchestrator()
app = FastAPI(title="Streaming S2S Telephony")

@app.on_event("startup")
async def startup():
    await orchestrator.start()

@app.on_event("shutdown")
async def shutdown():
    await orchestrator.stop()

@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "mode": "streaming_s2s",
        "active_calls": len(orchestrator.sessions)
    }

@app.post("/twilio/inbound")
async def twilio_inbound(
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...)
):
    """Handle incoming call."""
    print(f"📞 Inbound call: {CallSid} from {From}")
    orchestrator.create_session(CallSid)
    
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://cleans2s.voiceflow.cloud/twilio/stream" />
    </Connect>
</Response>"""
    
    return PlainTextResponse(content=twiml, media_type="application/xml")

@app.websocket("/twilio/stream")
async def twilio_websocket(websocket: WebSocket):
    """WebSocket for streaming audio."""
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
                
                session = orchestrator.get_session(call_sid)
                if session:
                    session.stream_sid = stream_sid
                    session.websocket = websocket
                    print(f"   📞 Call {call_sid[:20]}... started")
                    
                    # Send greeting (non-blocking)
                    asyncio.create_task(
                        orchestrator.stream_tts_to_twilio(
                            session,
                            async_generator(["Hello! Phil here. How can I help you?"])
                        )
                    )
                
            elif event == 'media':
                if not call_sid:
                    continue
                
                ulaw_chunk = base64.b64decode(data['media']['payload'])
                session = orchestrator.get_session(call_sid)
                
                if session:
                    await orchestrator.process_audio_chunk(session, ulaw_chunk)
                    
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


async def async_generator(items):
    """Helper to create async generator from list."""
    for item in items:
        yield item


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
