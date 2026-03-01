#!/usr/bin/env python3
"""
Mock ASR Server for Testing Pipeline Latency

Returns predetermined transcriptions with minimal latency.
Use this to test LLM+TTS latency without ASR bottlenecks.
"""

import os
import time
import base64
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uvicorn

app = FastAPI(title="Mock ASR Server (for testing)", version="1.0.0")


class ASRRequest(BaseModel):
    audio: str  # Base64-encoded (ignored in mock)
    sample_rate: int = 16000


class ASRResponse(BaseModel):
    text: str
    processing_time_ms: float


# Test phrases that exercise different aspects
TEST_PHRASES = [
    "Hello, how are you today?",
    "What is the weather like?",
    "Tell me a joke.",
    "What time is it?",
    "Thank you for your help.",
]
phrase_index = 0


@app.get("/health")
async def health():
    return {"status": "healthy", "mode": "mock", "latency_ms": "~1-5ms"}


@app.post("/v1/audio/transcriptions")
async def transcribe(request: ASRRequest):
    """Return mock transcription with minimal latency"""
    start = time.time()
    
    global phrase_index
    text = TEST_PHRASES[phrase_index % len(TEST_PHRASES)]
    phrase_index += 1
    
    processing_time = (time.time() - start) * 1000
    
    return ASRResponse(
        text=text,
        processing_time_ms=processing_time
    )


if __name__ == "__main__":
    port = int(os.environ.get("ASR_PORT", 8003))
    print(f"Mock ASR server starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
