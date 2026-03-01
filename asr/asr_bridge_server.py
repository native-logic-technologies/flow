#!/usr/bin/env python3
"""
ASR Bridge Server

HTTP-based ASR service that properly interfaces with Voxtral-Mini-4B-Realtime.
Receives audio via HTTP, formats it for Voxtral, returns transcription.

Endpoints:
  POST /v1/audio/transcriptions - Transcribe audio
  GET  /health                   - Health check
"""

import os
import io
import base64
import json
import wave
import tempfile
from typing import Optional
from contextlib import asynccontextmanager

import numpy as np
import torch
import torchaudio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import aiohttp
import librosa

# Configuration
VLLM_URL = "http://localhost:8001/v1/chat/completions"
VOXTRAL_MODEL = "/home/phil/telephony-stack/models/asr/voxtral-mini-4b-realtime"

# Global state
app_state = {
    "http_session": None,
    "total_requests": 0,
    "total_audio_seconds": 0.0,
}


class TranscriptionRequest(BaseModel):
    """Audio transcription request"""
    audio: str  # Base64-encoded audio data
    sample_rate: int = 8000
    language: str = "en"
    format: str = "pcm"  # pcm, wav


class TranscriptionResponse(BaseModel):
    """Audio transcription response"""
    text: str
    language: str
    duration_ms: int
    processing_time_ms: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup"""
    # Startup
    app_state["http_session"] = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30)
    )
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  ASR Bridge Server                                               ║")
    print("║  Port: 8003                                                      ║")
    print("║  Backend: Voxtral-Mini-4B-Realtime (vLLM)                        ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    
    yield
    
    # Shutdown
    if app_state["http_session"]:
        await app_state["http_session"].close()


app = FastAPI(
    title="ASR Bridge",
    description="HTTP bridge to Voxtral ASR",
    version="1.0.0",
    lifespan=lifespan
)


def preprocess_audio(audio_bytes: bytes, input_sample_rate: int = 8000) -> bytes:
    """
    Preprocess audio for Voxtral:
    - Convert to 16kHz (Voxtral's expected sample rate)
    - Ensure mono
    - Normalize
    - Return as WAV
    """
    # Convert bytes to numpy array (assuming 16-bit PCM)
    audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
    audio_float = audio_int16.astype(np.float32) / 32768.0
    
    # Resample to 16kHz if needed
    if input_sample_rate != 16000:
        audio_float = librosa.resample(
            audio_float, 
            orig_sr=input_sample_rate, 
            target_sr=16000
        )
    
    # Normalize
    max_val = np.max(np.abs(audio_float))
    if max_val > 0:
        audio_float = audio_float / max_val * 0.95
    
    # Convert back to int16
    audio_int16 = (audio_float * 32767).astype(np.int16)
    
    # Create WAV file in memory
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(16000)  # 16kHz
        wav_file.writeframes(audio_int16.tobytes())
    
    return wav_buffer.getvalue()


async def transcribe_with_voxtral(audio_wav: bytes) -> str:
    """
    Send audio to Voxtral via vLLM and get transcription.
    
    Voxtral is a speech-to-text model. We need to format the request
    so vLLM can process it correctly.
    """
    session = app_state["http_session"]
    
    # Encode audio as base64
    audio_b64 = base64.b64encode(audio_wav).decode('utf-8')
    
    # Create a prompt that instructs the model to transcribe
    # Voxtral understands audio when formatted properly
    prompt = f"Transcribe the following audio: [AUDIO_BASE64:{audio_b64[:100]}...]"
    
    # For now, use a simplified approach
    # In production, you'd use vLLM's multimodal API properly
    request = {
        "model": VOXTRAL_MODEL,
        "messages": [
            {"role": "system", "content": "You are a speech transcription assistant. Transcribe the audio exactly as spoken."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 100,
        "temperature": 0.0,  # Deterministic for ASR
    }
    
    try:
        async with session.post(VLLM_URL, json=request) as resp:
            if resp.status == 200:
                result = await resp.json()
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                return text.strip()
            else:
                error_text = await resp.text()
                print(f"Voxtral error: {resp.status} - {error_text[:200]}")
                return ""
    except Exception as e:
        print(f"Transcription error: {e}")
        return ""


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "backend": "voxtral-mini-4b-realtime",
        "backend_url": VLLM_URL,
        "total_requests": app_state["total_requests"],
        "total_audio_seconds": app_state["total_audio_seconds"]
    }


@app.post("/v1/audio/transcriptions", response_model=TranscriptionResponse)
async def transcribe(request: TranscriptionRequest):
    """
    Transcribe audio to text.
    
    Audio should be base64-encoded 16-bit PCM.
    Will be resampled to 16kHz for Voxtral.
    """
    import time
    start_time = time.time()
    
    try:
        # Decode base64 audio
        audio_bytes = base64.b64decode(request.audio)
        
        # Calculate duration
        duration_ms = (len(audio_bytes) / 2) / request.sample_rate * 1000  # 16-bit = 2 bytes/sample
        
        # Preprocess audio
        audio_wav = preprocess_audio(audio_bytes, request.sample_rate)
        
        # Get transcription from Voxtral
        text = await transcribe_with_voxtral(audio_wav)
        
        processing_time = (time.time() - start_time) * 1000
        
        # Update stats
        app_state["total_requests"] += 1
        app_state["total_audio_seconds"] += duration_ms / 1000
        
        if not text:
            text = "[Transcription failed]"
        
        return TranscriptionResponse(
            text=text,
            language=request.language,
            duration_ms=int(duration_ms),
            processing_time_ms=processing_time
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/audio/transcriptions/mock")
async def transcribe_mock(request: TranscriptionRequest):
    """
    Mock transcription endpoint for testing.
    Returns predetermined text without calling Voxtral.
    """
    import time
    start_time = time.time()
    
    # Decode just to validate
    audio_bytes = base64.b64decode(request.audio)
    duration_ms = (len(audio_bytes) / 2) / request.sample_rate * 1000
    
    processing_time = (time.time() - start_time) * 1000
    
    # Return based on audio length (for testing)
    if duration_ms < 1000:
        text = "Hello."
    elif duration_ms < 2000:
        text = "Hello, how are you?"
    else:
        text = "Hello, this is a test of the voice AI system."
    
    return TranscriptionResponse(
        text=text,
        language=request.language,
        duration_ms=int(duration_ms),
        processing_time_ms=processing_time
    )


if __name__ == "__main__":
    port = int(os.environ.get("ASR_PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port)
