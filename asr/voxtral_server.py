#!/usr/bin/env python3
"""
Voxtral-Mini-4B-Realtime-2602 ASR Server
Optimized for DGX Spark (GB10) Blackwell architecture

Port: 8001
Endpoint: POST /v1/audio/transcriptions
Input: Raw 16-bit PCM bytes (16kHz mono)
Output: {"text": "transcribed text"}
"""

import os
import torch
import numpy as np
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq
import uvicorn
import time
import logging

# Set HuggingFace cache to local directory to avoid permission issues
os.environ["HF_HOME"] = os.path.expanduser("~/telephony-stack/models/hf_cache")
os.environ["TRANSFORMERS_CACHE"] = os.path.expanduser("~/telephony-stack/models/hf_cache")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Global model and processor
processor = None
model = None

# Configuration
MODEL_ID = "mistralai/Voxtral-Mini-4B-Realtime-2602"
CACHE_DIR = os.path.expanduser("~/telephony-stack/models/hf_cache")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load Voxtral model on startup with Blackwell optimizations"""
    global processor, model
    
    logger.info("=" * 60)
    logger.info("Loading Voxtral-Mini-4B-Realtime-2602...")
    logger.info(f"Device: {DEVICE} | Dtype: {DTYPE}")
    logger.info(f"Cache: {CACHE_DIR}")
    logger.info("=" * 60)
    
    try:
        # Load processor with trust_remote_code for Voxtral's custom tokenizer
        processor = AutoProcessor.from_pretrained(
            MODEL_ID,
            trust_remote_code=True,
            cache_dir=CACHE_DIR
        )
        logger.info("✓ Processor loaded")
        
        # Load model with BF16 for Blackwell Tensor Cores
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            MODEL_ID,
            torch_dtype=DTYPE,
            trust_remote_code=True,
            cache_dir=CACHE_DIR,
            device_map="auto" if DEVICE == "cuda" else None
        )
        
        if DEVICE == "cuda" and not hasattr(model, 'device_map'):
            model = model.to(DEVICE)
            
        logger.info("✓ Model loaded to GPU")
        
        # BLACKWELL OPTIMIZATION: torch.compile
        # This fuses CUDA kernels and drops inference time by ~40%
        if DEVICE == "cuda" and hasattr(torch, 'compile'):
            logger.info("Compiling model for GB10 Tensor Cores...")
            try:
                model = torch.compile(model, mode="reduce-overhead", fullgraph=False)
                logger.info("✓ Model compiled")
            except Exception as e:
                logger.warning(f"torch.compile failed (continuing without): {e}")
        
        # Warmup inference
        logger.info("Warming up with dummy input...")
        dummy_audio = np.zeros(16000, dtype=np.float32)  # 1 second of silence
        inputs = processor(dummy_audio, sampling_rate=16000, return_tensors="pt")
        inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
        
        with torch.no_grad():
            _ = model.generate(**inputs, max_new_tokens=10)
        
        torch.cuda.synchronize() if DEVICE == "cuda" else None
        logger.info("✓ Warmup complete")
        logger.info("=" * 60)
        logger.info("Voxtral ASR Ready on Port 8001!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        raise
    
    yield
    
    # Cleanup
    logger.info("Shutting down Voxtral ASR server...")


app = FastAPI(title="Voxtral ASR", version="2602", lifespan=lifespan)


@app.post("/v1/audio/transcriptions")
async def transcribe_audio(request: Request):
    """
    Transcribe audio to text.
    
    Expects raw 16-bit PCM bytes (16kHz, mono, little-endian).
    Returns JSON with transcribed text.
    """
    start_time = time.time()
    
    try:
        # Receive raw PCM bytes from Rust
        pcm_bytes = await request.body()
        
        if len(pcm_bytes) == 0:
            return JSONResponse({"text": ""})
        
        # Convert 16-bit PCM to Float32 array (-1.0 to 1.0)
        audio_array = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Voxtral expects 16kHz audio (processor handles resampling if needed)
        inputs = processor(
            audio_array,
            sampling_rate=16000,
            return_tensors="pt"
        )
        
        # Move to GPU with BF16
        inputs = {k: v.to(DEVICE) if isinstance(v, torch.Tensor) else v for k, v in inputs.items()}
        
        # Generate transcript
        with torch.no_grad():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=128,  # Keep short for telephony
                use_cache=True,
                do_sample=False,     # Deterministic for speed
            )
        
        # Decode tokens to text
        transcript = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        transcript = transcript.strip()
        
        elapsed_ms = (time.time() - start_time) * 1000
        audio_duration_ms = (len(audio_array) / 16000) * 1000
        
        logger.info(
            f"Transcribed {audio_duration_ms:.0f}ms audio in {elapsed_ms:.1f}ms | "
            f"RTF: {elapsed_ms/audio_duration_ms:.2f}x | Text: '{transcript[:50]}{'...' if len(transcript) > 50 else ''}'"
        )
        
        return {"text": transcript}
        
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "model": MODEL_ID,
        "device": DEVICE,
        "dtype": str(DTYPE)
    }


@app.get("/")
async def root():
    """Root endpoint with info"""
    return {
        "service": "Voxtral-Mini-4B-Realtime-2602 ASR",
        "version": "2602",
        "endpoint": "POST /v1/audio/transcriptions",
        "format": "16-bit PCM @ 16kHz mono",
        "device": DEVICE,
        "dtype": str(DTYPE)
    }


if __name__ == "__main__":
    # Run with single worker for model sharing
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        workers=1,
        log_level="info"
    )
