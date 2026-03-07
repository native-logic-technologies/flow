"""
MOSS-TTS llama.cpp Backend Server
Torch-free TTS using llama.cpp + NumPy + ONNX Runtime
"""

import os
import sys
import logging
from pathlib import Path

# Setup logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Set up Python path for MOSS-TTS
MOSS_SRC = Path("/home/phil/telephony-stack/moss-tts-src")
sys.path.insert(0, str(MOSS_SRC))

# Set up library path for llama.cpp
os.environ["LD_LIBRARY_PATH"] = "/home/phil/telephony-stack/llama.cpp/build/lib:" + os.environ.get("LD_LIBRARY_PATH", "")

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="MOSS-TTS llama.cpp Server", version="1.0.0")

# Global pipeline instance
pipeline = None

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    speed: Optional[float] = 1.0
    format: Optional[str] = "pcm"
    
class TTSResponse(BaseModel):
    status: str
    samples: int
    sample_rate: int
    duration_seconds: float
    generation_time_seconds: float

@app.on_event("startup")
async def startup_event():
    """Initialize the TTS pipeline on startup."""
    global pipeline
    
    logger.info("Initializing MOSS-TTS llama.cpp pipeline...")
    
    try:
        from moss_tts_delay.llama_cpp.pipeline import LlamaCppPipeline, PipelineConfig
        
        config = PipelineConfig(
            backbone_gguf="/home/phil/telephony-stack/models/tts-gguf/MOSS_TTS_backbone_q8_0.gguf",
            embedding_dir="/home/phil/telephony-stack/models/tts-gguf/embeddings",
            lm_head_dir="/home/phil/telephony-stack/models/tts-gguf/lm_heads",
            tokenizer_dir="/home/phil/telephony-stack/models/tts/moss-tts-realtime",
            audio_backend="onnx",
            audio_encoder_onnx="/home/phil/telephony-stack/models/tts-gguf/onnx_tokenizer/encoder.onnx",
            audio_decoder_onnx="/home/phil/telephony-stack/models/tts-gguf/onnx_tokenizer/decoder.onnx",
            n_gpu_layers=99,
            n_ctx=4096,
            heads_backend="numpy",
            max_new_tokens=2000
        )
        
        pipeline = LlamaCppPipeline(config)
        logger.info("✅ Pipeline initialized successfully!")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize pipeline: {e}")
        raise

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy" if pipeline else "initializing",
        "backend": "llama.cpp",
        "gpu_layers": 99
    }

@app.post("/v1/audio/speech")
async def create_speech(request: TTSRequest):
    """
    OpenAI-compatible TTS endpoint.
    Returns 24kHz PCM audio (mono, 16-bit).
    """
    global pipeline
    
    if not pipeline:
        raise HTTPException(status_code=503, detail="TTS pipeline not initialized")
    
    try:
        import time
        
        logger.info(f"Generating TTS for: '{request.text[:50]}...'")
        
        t0 = time.time()
        audio = pipeline.generate(request.text)
        gen_time = time.time() - t0
        
        # Convert to 16-bit PCM
        audio_pcm = (audio * 32767).astype(np.int16)
        
        logger.info(f"✅ Generated {len(audio)} samples in {gen_time:.2f}s "
                   f"({gen_time/(len(audio)/24000):.2f}x real-time)")
        
        return Response(
            content=audio_pcm.tobytes(),
            media_type="audio/pcm",
            headers={
                "X-Sample-Rate": "24000",
                "X-Duration": str(len(audio)/24000),
                "X-Generation-Time": str(gen_time)
            }
        )
        
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate", response_model=TTSResponse)
async def generate(request: TTSRequest):
    """Direct generation endpoint with metadata."""
    global pipeline
    
    if not pipeline:
        raise HTTPException(status_code=503, detail="TTS pipeline not initialized")
    
    try:
        import time
        
        t0 = time.time()
        audio = pipeline.generate(request.text)
        gen_time = time.time() - t0
        
        # Save to temp file for retrieval
        audio_pcm = (audio * 32767).astype(np.int16)
        
        return TTSResponse(
            status="success",
            samples=len(audio),
            sample_rate=24000,
            duration_seconds=len(audio)/24000,
            generation_time_seconds=gen_time
        )
        
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5002,
        log_level="info"
    )
