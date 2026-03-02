#!/usr/bin/env python3
"""
Parakeet ASR Bridge Server

HTTP-based ASR service that interfaces with NVIDIA Parakeet-1.1B-RNNT via gRPC.
Receives audio via HTTP, streams to Parakeet, returns transcription.

Endpoints:
  POST /v1/audio/transcriptions - Transcribe audio
  GET  /health                   - Health check
"""

import os
import io
import base64
import json
import wave
import time
from typing import Optional
from contextlib import asynccontextmanager

import numpy as np
import grpc
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Import Riva proto definitions
# These come from nvidia-riva-client or we can define minimal ones
import riva.client

# Configuration
PARAKEET_GRPC_URL = os.environ.get("PARAKEET_GRPC_URL", "localhost:50051")

# Global state
app_state = {
    "auth": None,
    "total_requests": 0,
    "total_audio_seconds": 0.0,
}


class TranscriptionRequest(BaseModel):
    """Audio transcription request"""
    audio: str  # Base64-encoded audio data (16-bit PCM)
    sample_rate: int = 8000
    language: str = "en-US"
    format: str = "pcm"


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
    app_state["auth"] = riva.client.Auth(uri=PARAKEET_GRPC_URL)
    
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  Parakeet ASR Bridge Server                                      ║")
    print(f"║  Port: 8003                                                      ║")
    print(f"║  Backend: Parakeet-1.1B-RNNT (gRPC: {PARAKEET_GRPC_URL})      ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    
    yield
    
    # Shutdown
    print("Shutting down Parakeet ASR Bridge...")


app = FastAPI(
    title="Parakeet ASR Bridge",
    description="HTTP bridge to NVIDIA Parakeet ASR via gRPC",
    version="1.0.0",
    lifespan=lifespan
)


def preprocess_audio(audio_bytes: bytes, input_sample_rate: int = 8000) -> bytes:
    """
    Preprocess audio for Parakeet:
    - Parakeet expects 16kHz, mono, 16-bit PCM
    - Resample if needed
    """
    # Convert bytes to numpy array (16-bit PCM)
    audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
    audio_float = audio_int16.astype(np.float32) / 32768.0
    
    # Resample to 16kHz if needed
    if input_sample_rate != 16000:
        import librosa
        audio_float = librosa.resample(
            audio_float,
            orig_sr=input_sample_rate,
            target_sr=16000
        )
    
    # Convert back to int16
    audio_int16 = (audio_float * 32767).astype(np.int16)
    
    return audio_int16.tobytes()


def transcribe_with_parakeet(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """
    Send audio to Parakeet via gRPC and get transcription.
    """
    auth = app_state["auth"]
    
    # Create ASR service client
    asr_service = riva.client.ASRService(auth)
    
    # Configure recognition
    config = riva.client.StreamingRecognitionConfig(
        config=riva.client.RecognitionConfig(
            encoding=riva.client.AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=sample_rate,
            language_code="en-US",
            max_alternatives=1,
            enable_automatic_punctuation=True,
        ),
        interim_results=False,  # We only want final results
    )
    
    # Generate streaming config request
    yield config
    
    # Stream audio chunks
    chunk_size = 1600  # 100ms at 16kHz
    for i in range(0, len(audio_bytes), chunk_size * 2):  # 2 bytes per sample
        chunk = audio_bytes[i:i + chunk_size * 2]
        if chunk:
            yield riva.client.AudioChunk(audio=chunk)


def transcribe_sync(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """
    Synchronous transcription using Parakeet.
    """
    auth = app_state["auth"]
    asr_service = riva.client.ASRService(auth)
    
    # Configure recognition
    config = riva.client.RecognitionConfig(
        encoding=riva.client.AudioEncoding.LINEAR_PCM,
        sample_rate_hertz=sample_rate,
        language_code="en-US",
        max_alternatives=1,
        enable_automatic_punctuation=True,
    )
    
    # Use offline recognition for short utterances
    # This is simpler than streaming for telephony-style turn-based interaction
    try:
        response = asr_service.offline_recognize(audio_bytes, config)
        
        # Extract transcript from response
        transcripts = []
        for result in response.results:
            if result.alternatives:
                transcripts.append(result.alternatives[0].transcript)
        
        return " ".join(transcripts).strip()
    except Exception as e:
        print(f"Parakeet transcription error: {e}")
        return ""


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "backend": "parakeet-1.1b-rnnt",
        "backend_url": PARAKEET_GRPC_URL,
        "total_requests": app_state["total_requests"],
        "total_audio_seconds": app_state["total_audio_seconds"]
    }


@app.post("/v1/audio/transcriptions", response_model=TranscriptionResponse)
async def transcribe(request: TranscriptionRequest):
    """
    Transcribe audio to text using Parakeet ASR.
    
    Audio should be base64-encoded 16-bit PCM.
    Will be resampled to 16kHz for Parakeet.
    """
    start_time = time.time()
    
    try:
        # Decode base64 audio
        audio_bytes = base64.b64decode(request.audio)
        
        # Calculate duration
        duration_ms = (len(audio_bytes) / 2) / request.sample_rate * 1000
        
        # Preprocess audio (resample to 16kHz)
        if request.sample_rate != 16000:
            audio_bytes = preprocess_audio(audio_bytes, request.sample_rate)
            sample_rate = 16000
        else:
            sample_rate = request.sample_rate
        
        # Get transcription from Parakeet
        text = transcribe_sync(audio_bytes, sample_rate)
        
        processing_time = (time.time() - start_time) * 1000
        
        # Update stats
        app_state["total_requests"] += 1
        app_state["total_audio_seconds"] += duration_ms / 1000
        
        if not text:
            text = "[No speech detected]"
        
        return TranscriptionResponse(
            text=text,
            language=request.language,
            duration_ms=int(duration_ms),
            processing_time_ms=processing_time
        )
        
    except Exception as e:
        import traceback
        print(f"Transcription error: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/audio/transcriptions/mock")
async def transcribe_mock(request: TranscriptionRequest):
    """Mock endpoint for testing"""
    audio_bytes = base64.b64decode(request.audio)
    duration_ms = (len(audio_bytes) / 2) / request.sample_rate * 1000
    
    # Return based on audio length
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
        processing_time_ms=50.0
    )


if __name__ == "__main__":
    port = int(os.environ.get("ASR_PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port)
