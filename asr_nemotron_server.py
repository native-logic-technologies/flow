#!/usr/bin/env python3
"""
Nemotron Speech Streaming ASR Server
FastAPI wrapper for nvidia/nemotron-speech-streaming-en-0.6b
"""

import os
os.environ['HF_HOME'] = '/tmp/hf_cache'

import io
import json
import wave
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Global model instance
asr_pipeline = None

def load_asr_model():
    """Load the Nemotron ASR model"""
    global asr_pipeline
    
    print("🎤 Loading Nemotron Speech Streaming ASR...")
    print(f"   Model: nvidia/nemotron-speech-streaming-en-0.6b")
    
    try:
        from omegaconf import OmegaConf
        from nemo.collections.asr.inference.factory.pipeline_builder import PipelineBuilder
        
        # Load config
        cfg_path = '/home/phil/telephony-stack/models/asr/nemotron-streaming/cache_aware_rnnt.yaml'
        cfg = OmegaConf.load(cfg_path)
        
        # Override with our model path
        cfg.asr.model_name = '/home/phil/telephony-stack/models/asr/nemotron-streaming/nemotron-speech-streaming-en-0.6b.nemo'
        cfg.asr.device = 'cuda'
        cfg.asr.device_id = 0
        cfg.asr.compute_dtype = 'bfloat16'
        
        # Build pipeline
        asr_pipeline = PipelineBuilder.build_pipeline(cfg)
        
        print("✅ Nemotron ASR loaded successfully!")
        print(f"   Device: {cfg.asr.device}")
        print(f"   Dtype: {cfg.asr.compute_dtype}")
        
    except Exception as e:
        print(f"❌ Failed to load ASR model: {e}")
        import traceback
        traceback.print_exc()
        raise

class ASRRequest(BaseModel):
    audio: str = Field(..., description="Base64-encoded WAV audio data (16kHz mono)")
    language: Optional[str] = Field("en", description="Language code")

class ASRResponse(BaseModel):
    text: str
    language: Optional[str] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup"""
    load_asr_model()
    yield
    # Cleanup
    global asr_pipeline
    if asr_pipeline:
        del asr_pipeline
    torch.cuda.empty_cache()

app = FastAPI(
    title="Nemotron Speech Streaming ASR",
    description="Real-time ASR using nvidia/nemotron-speech-streaming-en-0.6b",
    version="1.0.0",
    lifespan=lifespan
)

def decode_audio(audio_b64: str) -> tuple[np.ndarray, int]:
    """Decode base64 WAV to numpy array"""
    import base64
    audio_bytes = base64.b64decode(audio_b64)
    
    with io.BytesIO(audio_bytes) as wav_io:
        with wave.open(wav_io, 'rb') as wav_file:
            n_channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            n_frames = wav_file.getnframes()
            
            raw_data = wav_file.readframes(n_frames)
            
            if sample_width == 2:
                audio_np = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
            else:
                raise ValueError(f"Unsupported sample width: {sample_width}")
            
            if n_channels == 2:
                audio_np = audio_np.reshape(-1, 2).mean(axis=1)
    
    return audio_np, sample_rate

@app.post("/v1/audio/transcriptions", response_model=ASRResponse)
async def transcribe_audio(request: ASRRequest):
    """Transcribe audio to text"""
    global asr_pipeline
    
    if asr_pipeline is None:
        raise HTTPException(status_code=503, detail="ASR model not loaded")
    
    try:
        # Decode audio
        audio_np, sample_rate = decode_audio(request.audio)
        
        # Save to temp file (NeMo expects file paths)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp_path = tmp.name
            import wave
            with wave.open(tmp_path, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes((audio_np * 32767).astype(np.int16).tobytes())
        
        # Run inference
        output = asr_pipeline.run([tmp_path])
        
        # Cleanup temp file
        os.unlink(tmp_path)
        
        # Extract text - output is a dict with integer keys
        text = ""
        if isinstance(output, dict):
            # NeMo pipeline returns {0: {...}, 1: {...}}
            first_result = output.get(0, {})
            if isinstance(first_result, dict):
                text = first_result.get('text', '')
        elif isinstance(output, list) and len(output) > 0:
            # Fallback for list format
            first_result = output[0]
            if isinstance(first_result, dict):
                text = first_result.get('text', '')
        
        return ASRResponse(text=text.strip(), language=request.language)
        
    except Exception as e:
        print(f"Transcription error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy" if asr_pipeline else "loading",
        "model": "nvidia/nemotron-speech-streaming-en-0.6b",
        "device": "cuda" if torch.cuda.is_available() else "cpu"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
