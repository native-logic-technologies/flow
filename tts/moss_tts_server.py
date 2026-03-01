#!/usr/bin/env python3
"""
MOSS-TTS-Realtime Native PyTorch Server
Fallback since vLLM doesn't support the custom moss_tts_realtime architecture
"""

import os
import sys
import torch
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

# Add model path for custom code
sys.path.insert(0, os.path.expanduser("~/telephony-stack/models/tts/moss-tts-realtime"))

app = FastAPI(title="MOSS-TTS-Realtime Server")

# Global model instance
model = None
tokenizer = None


class TTSRequest(BaseModel):
    model: str = "OpenMOSS-Team/MOSS-TTS-Realtime"
    input: str
    voice: str = "default_female"
    response_format: str = "pcm"
    speed: float = 1.0


def load_model():
    """Load MOSS-TTS model using native Transformers"""
    global model, tokenizer
    
    model_path = os.path.expanduser("~/telephony-stack/models/tts/moss-tts-realtime")
    
    print(f"Loading MOSS-TTS from {model_path}...")
    
    # Import after path setup
    from transformers import AutoModel, AutoTokenizer
    
    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        model_path,
        trust_remote_code=True
    )
    
    # Load model
    model = AutoModel.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True
    )
    
    model.eval()
    print(f"✓ MOSS-TTS loaded on {model.device}")


@app.on_event("startup")
async def startup_event():
    load_model()


@app.get("/health")
async def health():
    return {"status": "healthy", "model": "MOSS-TTS-Realtime"}


@app.post("/v1/audio/speech")
async def text_to_speech(request: TTSRequest):
    """
    OpenAI-compatible TTS endpoint
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Tokenize input
        inputs = tokenizer(request.input, return_tensors="pt")
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        
        # Generate audio
        with torch.no_grad():
            # MOSS-TTS specific generation
            # This is a simplified version - actual implementation depends on model API
            outputs = model.generate(
                **inputs,
                max_length=8192,
                do_sample=True,
                temperature=0.7
            )
        
        # Convert to PCM audio bytes
        # Note: Actual audio decoding depends on model output format
        audio_bytes = outputs.cpu().numpy().tobytes()
        
        return StreamingResponse(
            iter([audio_bytes]),
            media_type="audio/pcm",
            headers={
                "Content-Type": "audio/pcm",
                "X-Model": "MOSS-TTS-Realtime"
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/chat/completions")
async def chat_completions(request: dict):
    """
    Dummy endpoint for compatibility
    """
    return {
        "id": "chatcmpl-moss-tts",
        "object": "chat.completion",
        "created": 0,
        "model": "MOSS-TTS-Realtime",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "This is a TTS model. Use /v1/audio/speech endpoint."
            },
            "finish_reason": "stop"
        }]
    }


if __name__ == "__main__":
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  MOSS-TTS-Realtime Native Server (Non-vLLM)                        ║")
    print("║  Port: 8002                                                        ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    print("Note: Using native PyTorch since vLLM doesn't support moss_tts_realtime architecture")
    print()
    
    uvicorn.run(app, host="0.0.0.0", port=8002)
