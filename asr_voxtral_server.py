#!/usr/bin/env python3
"""
Voxtral ASR Server - FastAPI Wrapper for Voxtral Realtime
Optimized for DGX Spark (GB10) Blackwell Architecture

Replaces Qwen2.5-Omni on port 8001 with proper ASR capabilities.
"""

import os
os.environ['HF_HOME'] = '/tmp/hf_cache'
os.environ['TRANSFORMERS_CACHE'] = '/tmp/hf_cache'

import io
import json
import base64
import wave
import tempfile
from typing import Optional
from contextlib import asynccontextmanager

import torch
import torchaudio
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Global model instances
processor = None
model = None
device = None

class ASRRequest(BaseModel):
    audio: str = Field(..., description="Base64-encoded WAV audio data")
    language: Optional[str] = Field("en", description="Language code (en, ar, etc.)")
    task: str = Field("transcribe", description="Task: transcribe or translate")

class ASRResponse(BaseModel):
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load Voxtral model on startup"""
    global processor, model, device
    
    print("🚀 Loading Voxtral ASR model...")
    print(f"   PyTorch: {torch.__version__}")
    print(f"   CUDA: {torch.version.cuda}")
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"   Device: {device}")
    
    if torch.cuda.is_available():
        print(f"   GPU: {torch.cuda.get_device_name(0)}")
        # Set memory fraction for MPS isolation
        torch.cuda.set_per_process_memory_fraction(0.15)  # 15% for Voxtral
    
    model_path = "/home/phil/telephony-stack/models/asr/voxtral-mini-4b-realtime"
    
    try:
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
        
        print(f"   Loading processor from {model_path}...")
        processor = AutoProcessor.from_pretrained(model_path)
        
        print(f"   Loading model (this may take 30-60s)...")
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
            device_map=device,
            low_cpu_mem_usage=True,
        )
        model.eval()
        
        print(f"✅ Voxtral ASR loaded successfully!")
        print(f"   Model: Voxtral Mini 4B Realtime")
        print(f"   Dtype: bfloat16")
        print(f"   Ready for transcription on port 8001")
        
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    yield
    
    # Cleanup
    print("Shutting down Voxtral ASR...")
    if model:
        del model
    if processor:
        del processor
    torch.cuda.empty_cache()

app = FastAPI(
    title="Voxtral ASR Service",
    description="Real-time speech recognition for Native Logic telephony stack",
    version="1.0.0",
    lifespan=lifespan
)

def decode_audio(audio_b64: str) -> tuple[np.ndarray, int]:
    """Decode base64 WAV to numpy array"""
    audio_bytes = base64.b64decode(audio_b64)
    
    # Parse WAV file
    with io.BytesIO(audio_bytes) as wav_io:
        with wave.open(wav_io, 'rb') as wav_file:
            n_channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            n_frames = wav_file.getnframes()
            
            # Read raw audio data
            raw_data = wav_file.readframes(n_frames)
            
            # Convert to numpy
            if sample_width == 2:
                audio_np = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
            else:
                raise ValueError(f"Unsupported sample width: {sample_width}")
            
            # Convert to mono if stereo
            if n_channels == 2:
                audio_np = audio_np.reshape(-1, 2).mean(axis=1)
    
    return audio_np, sample_rate

@app.post("/v1/audio/transcriptions", response_model=ASRResponse)
async def transcribe_audio(request: ASRRequest):
    """Transcribe audio to text (OpenAI-compatible endpoint)"""
    if model is None or processor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Decode audio
        audio_np, sample_rate = decode_audio(request.audio)
        
        # Resample to 16kHz if needed (Voxtral expects 16kHz)
        if sample_rate != 16000:
            audio_tensor = torch.from_numpy(audio_np).unsqueeze(0)
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            audio_tensor = resampler(audio_tensor)
            audio_np = audio_tensor.squeeze().numpy()
        
        # Process through Voxtral
        inputs = processor(
            audio_np,
            sampling_rate=16000,
            return_tensors="pt"
        ).to(device)
        
        # Generate transcription
        with torch.no_grad():
            with torch.cuda.amp.autocast(dtype=torch.bfloat16):
                generated_ids = model.generate(
                    **inputs,
                    max_new_tokens=128,
                    language=request.language,
                    task=request.task,
                )
        
        # Decode transcription
        transcription = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        
        return ASRResponse(
            text=transcription.strip(),
            language=request.language,
            confidence=None  # Voxtral doesn't provide confidence scores
        )
        
    except Exception as e:
        print(f"Transcription error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# OpenAI-compatible chat completions endpoint for audio
class ChatMessage(BaseModel):
    role: str
    content: list | str

class ChatRequest(BaseModel):
    model: str = "voxtral-asr"
    messages: list[ChatMessage]
    max_tokens: int = 128
    temperature: float = 0.0

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    """OpenAI-compatible endpoint that accepts audio"""
    if model is None or processor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Extract audio from messages
        audio_b64 = None
        prompt_text = "Transcribe the audio"
        
        for msg in request.messages:
            if isinstance(msg.content, list):
                for item in msg.content:
                    if isinstance(item, dict):
                        if item.get("type") == "input_audio":
                            audio_b64 = item.get("input_audio", {}).get("data")
                        elif item.get("type") == "text":
                            prompt_text = item.get("text", prompt_text)
        
        if audio_b64 is None:
            # No audio provided - return error
            return JSONResponse({
                "id": "chatcmpl-error",
                "object": "chat.completion",
                "created": 0,
                "model": request.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "No audio provided for transcription."
                    },
                    "finish_reason": "stop"
                }]
            })
        
        # Decode and transcribe
        audio_np, sample_rate = decode_audio(audio_b64)
        
        # Resample to 16kHz if needed
        if sample_rate != 16000:
            audio_tensor = torch.from_numpy(audio_np).unsqueeze(0)
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            audio_tensor = resampler(audio_tensor)
            audio_np = audio_tensor.squeeze().numpy()
        
        # Process through Voxtral
        inputs = processor(
            audio_np,
            sampling_rate=16000,
            return_tensors="pt"
        ).to(device)
        
        with torch.no_grad():
            with torch.cuda.amp.autocast(dtype=torch.bfloat16):
                generated_ids = model.generate(**inputs, max_new_tokens=request.max_tokens)
        
        transcription = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        
        return JSONResponse({
            "id": "chatcmpl-voxtral",
            "object": "chat.completion",
            "created": 0,
            "model": request.model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": transcription.strip()
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        })
        
    except Exception as e:
        print(f"Chat completion error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy" if model else "loading",
        "model": "voxtral-mini-4b-realtime",
        "device": str(device),
        "dtype": "bfloat16"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
