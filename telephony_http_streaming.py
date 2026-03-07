#!/usr/bin/env python3
"""
HTTP Streaming S2S - Uses PCM streaming for TTS (more reliable than WebSocket)
ASR: Parakeet-RNNT via Riva gRPC (port 50051)
"""

import os
os.environ['HF_HOME'] = '/tmp/hf_cache'

import asyncio
import audioop
import base64
import io
import json
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import aiohttp
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import PlainTextResponse, StreamingResponse

# Import ASR clients - Nemotron is primary
try:
    from asr_parakeet_client import ParakeetASRClient
    HAS_PARAKEET = True
except ImportError:
    HAS_PARAKEET = False

# Nemotron ASR endpoint
NEMOTRON_ASR_URL = "http://localhost:8004/v1/audio/transcriptions"

BRAIN_URL = "http://localhost:8000/v1/chat/completions"
VOICE_URL = "http://localhost:8002/v1/audio/speech"

# Pre-cached audio files for instant playback (avoids TTS latency)
CACHED_INTRO_PCM_24K = "/tmp/intro_audio.pcm"  # Pre-generated Phil intro

TARGET_RATE = 16000
SILENCE_THRESHOLD = 0.01
MIN_UTTERANCE_MS = 500
MAX_UTTERANCE_MS = 8000

class AudioProcessor:
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
        # Resample 24kHz -> 16kHz -> 8kHz, then convert to μ-law
        pcm_16k = audioop.ratecv(pcm_24k, 2, 1, 24000, 16000, None)[0]
        pcm_8k = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)[0]
        return audioop.lin2ulaw(pcm_8k, 2)
    
    @staticmethod
    def calculate_energy(pcm_bytes: bytes) -> float:
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return np.abs(audio).mean()


@dataclass
class CallSession:
    call_sid: str
    stream_sid: Optional[str] = None
    websocket: Optional[WebSocket] = None
    created_at: datetime = field(default_factory=datetime.now)
    history: deque = field(default_factory=lambda: deque(maxlen=10))
    audio_buffer: bytearray = field(default_factory=bytearray)
    silence_duration_ms: float = 0.0
    is_processing: bool = False
    
    system_prompt: str = "You are Phil, a helpful AI assistant. Be warm and concise."


class StreamingOrchestrator:
    def __init__(self):
        self.sessions = {}
        self.http_session = None
        self.audio_processor = AudioProcessor()
        self.asr_client = None
        
    async def start(self):
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
            headers={"Content-Type": "application/json"}
        )
        
        # Initialize Parakeet ASR client
        if HAS_PARAKEET:
            try:
                self.asr_client = ParakeetASRClient("localhost:50051")
                print("🎤 Parakeet ASR connected (localhost:50051)")
            except Exception as e:
                print(f"⚠️  Parakeet ASR unavailable: {e}")
                self.asr_client = None
        
        print("🚀 HTTP Streaming Orchestrator initialized")
        
    async def stop(self):
        if self.http_session:
            await self.http_session.close()
            
    def create_session(self, call_sid: str):
        session = CallSession(call_sid=call_sid)
        self.sessions[call_sid] = session
        return session
        
    def get_session(self, call_sid: str):
        return self.sessions.get(call_sid)
        
    def remove_session(self, call_sid: str):
        self.sessions.pop(call_sid, None)
    
    async def transcribe(self, pcm_16k: bytes) -> Optional[str]:
        """ASR using Nemotron Speech Streaming (port 8004)."""
        try:
            # Create WAV from PCM
            import io
            import base64
            import wave
            
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm_16k)
            
            audio_b64 = base64.b64encode(wav_buffer.getvalue()).decode()
            
            # Call Nemotron ASR
            payload = {
                "audio": audio_b64,
                "language": "en"
            }
            
            async with self.http_session.post(NEMOTRON_ASR_URL, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    text = result.get("text", "").strip()
                    if text:
                        print(f"   🎤 Nemotron ASR: '{text[:60]}...'")
                        return text
                else:
                    error_text = await resp.text()
                    print(f"   ⚠️  Nemotron ASR error {resp.status}: {error_text[:100]}")
            
            return None
                
        except Exception as e:
            print(f"   ❌ ASR error: {e}")
            return None
    
    async def generate_response(self, session: CallSession, user_text: str) -> str:
        """Generate LLM response (non-streaming for reliability)."""
        messages = [{"role": "system", "content": session.system_prompt}]
        for turn in list(session.history)[-6:]:
            messages.append({"role": turn.get("role", "user"), "content": turn["text"]})
        messages.append({"role": "user", "content": user_text})
        
        payload = {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "messages": messages,
            "max_tokens": 60,
            "temperature": 0.7
        }
        
        try:
            async with self.http_session.post(BRAIN_URL, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result['choices'][0]['message']['content']
        except Exception as e:
            print(f"   ❌ LLM: {e}")
        return "I'm sorry, I didn't catch that."
    
    async def synthesize_streaming(
        self, 
        session: CallSession,
        text: str
    ):
        """
        Stream TTS using HTTP PCM endpoint.
        Converts PCM chunks to μ-law and sends to Twilio immediately.
        """
        if not session.websocket or not session.stream_sid:
            return
        
        try:
            payload = {
                "input": text,
                "voice": "phil",  # Uses cached embedding
                "response_format": "pcm",  # Stream PCM chunks
                "speed": 1.0
            }
            
            print(f"   🎙️  Streaming TTS...")
            
            async with self.http_session.post(
                VOICE_URL, 
                json=payload,
                timeout=60
            ) as resp:
                if resp.status != 200:
                    print(f"   ❌ TTS error: {resp.status}")
                    return
                
                chunk_count = 0
                # MOSS-TTS outputs 24kHz, need to resample to 8kHz μ-law for Twilio
                async for pcm_chunk in resp.content.iter_chunked(480):  # 10ms @ 24kHz
                    if pcm_chunk:
                        # Resample 24kHz -> 8kHz -> μ-law
                        ulaw = self.audio_processor.resample_24k_to_ulaw(pcm_chunk)
                        
                        # Send to Twilio immediately
                        await session.websocket.send_json({
                            "event": "media",
                            "streamSid": session.stream_sid,
                            "media": {"payload": base64.b64encode(ulaw).decode()}
                        })
                        chunk_count += 1
                
                print(f"   ✅ Streamed {chunk_count} chunks")
                
        except Exception as e:
            print(f"   ❌ TTS stream error: {e}")
    
    async def process_audio_chunk(self, session: CallSession, ulaw_chunk: bytes) -> bool:
        """Process incoming audio."""
        if session.is_processing:
            return False
        
        pcm_8k = self.audio_processor.ulaw_to_pcm(ulaw_chunk)
        pcm_16k = self.audio_processor.resample_8k_to_16k(pcm_8k)
        
        session.audio_buffer.extend(pcm_16k)
        energy = self.audio_processor.calculate_energy(pcm_16k)
        buffer_duration_ms = len(session.audio_buffer) / (TARGET_RATE * 2) * 1000
        
        if energy < SILENCE_THRESHOLD:
            session.silence_duration_ms += 20
        else:
            session.silence_duration_ms = 0
        
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
            # ASR
            print(f"👂 [{session.call_sid[:16]}...] Transcribing...")
            text = await self.transcribe(pcm_16k)
            if not text:
                session.is_processing = False
                return
            
            print(f"   📝 '{text[:50]}...'")
            
            # LLM
            print(f"   💬 Generating response...")
            response = await self.generate_response(session, text)
            print(f"   💬 '{response[:50]}...'")
            
            # TTS (streaming)
            await self.synthesize_streaming(session, response)
            
            # Update history
            session.history.append({"role": "user", "text": text})
            session.history.append({"role": "assistant", "text": response})
            
            print(f"   ✅ Done")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
        finally:
            session.is_processing = False


# ============== FastAPI App ==============

orchestrator = StreamingOrchestrator()
app = FastAPI(title="HTTP Streaming S2S")

@app.on_event("startup")
async def startup():
    await orchestrator.start()

@app.on_event("shutdown")
async def shutdown():
    await orchestrator.stop()

@app.get("/health")
async def health():
    return {"status": "healthy", "mode": "http_streaming"}

@app.post("/twilio/inbound")
async def inbound(CallSid: str = Form(...), From: str = Form(...)):
    print(f"📞 Call from {From}")
    orchestrator.create_session(CallSid)
    
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://cleans2s.voiceflow.cloud/twilio/stream" />
    </Connect>
</Response>"""
    
    return PlainTextResponse(content=twiml, media_type="application/xml")

@app.websocket("/twilio/stream")
async def stream(websocket: WebSocket):
    await websocket.accept()
    print("🔌 Connected")
    
    call_sid = None
    stream_sid = None
    
    try:
        while True:
            msg = await websocket.receive_text()
            data = json.loads(msg)
            event = data.get('event')
            
            if event == 'start':
                call_sid = data['start']['callSid']
                stream_sid = data['start']['streamSid']
                session = orchestrator.get_session(call_sid)
                if session:
                    session.stream_sid = stream_sid
                    session.websocket = websocket
                    print(f"   📞 Started")
                    
                    # Send greeting
                    asyncio.create_task(
                        orchestrator.synthesize_streaming(
                            session,
                            "Hello! Phil here from Native Logic. How can I help you?"
                        )
                    )
            
            elif event == 'media':
                if call_sid:
                    ulaw = base64.b64decode(data['media']['payload'])
                    session = orchestrator.get_session(call_sid)
                    if session:
                        await orchestrator.process_audio_chunk(session, ulaw)
            
            elif event == 'stop':
                print("   📴 Ended")
                if call_sid:
                    orchestrator.remove_session(call_sid)
                break
                
    except WebSocketDisconnect:
        print("🔌 Disconnected")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if call_sid:
            orchestrator.remove_session(call_sid)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
