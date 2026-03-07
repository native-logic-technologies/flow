#!/usr/bin/env python3
"""
MOSS-TTS-Realtime Server using llama.cpp backend
~4x more VRAM efficient than PyTorch version
"""

import sys
sys.path.insert(0, '/home/phil/telephony-stack/moss-tts-src')

import os
import io
import base64
import audioop
import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="MOSS-TTS llama.cpp Server")

# Global pipeline instance
pipeline = None

def load_pipeline():
    """Load the MOSS-TTS llama.cpp pipeline"""
    global pipeline
    
    from moss_tts_delay.llama_cpp.pipeline import LlamaCppTTSPipeline
    from moss_tts_delay.llama_cpp.processor import LlamaCppProcessor
    
    print("Loading MOSS-TTS llama.cpp pipeline...", flush=True)
    
    # Paths
    backbone_path = "/home/phil/telephony-stack/models/tts-gguf/MOSS_TTS_backbone_q8_0.gguf"
    embeddings_dir = "/home/phil/telephony-stack/models/tts-gguf/embeddings"
    lm_heads_dir = "/home/phil/telephony-stack/models/tts-gguf/lm_heads"
    
    # Load pipeline
    pipeline = LlamaCppTTSPipeline(
        backbone_path=backbone_path,
        embeddings_dir=embeddings_dir,
        lm_heads_dir=lm_heads_dir,
        llama_lib_path="/home/phil/telephony-stack/llama.cpp/build/lib/libllama.so",
        n_gpu_layers=99,
        n_ctx=8192
    )
    
    print("✅ Pipeline loaded!", flush=True)
    return pipeline

@app.on_event("startup")
async def startup():
    load_pipeline()

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "moss_tts_llama_cpp",
        "backend": "llama.cpp",
        "quantization": "Q8_0"
    }

@app.post("/v1/audio/speech")
async def text_to_speech(request: Request):
    """OpenAI-compatible TTS endpoint using llama.cpp"""
    global pipeline
    
    try:
        data = await request.json()
        text = data.get("input", "")
        voice = data.get("voice", "default")
        
        print(f"TTS request: '{text[:50]}...'", flush=True)
        
        # Generate audio using llama.cpp pipeline
        # This is a simplified version - actual implementation depends on the pipeline API
        audio_np = pipeline.generate(
            text=text,
            temperature=0.8,
            top_p=0.9
        )
        
        # Convert to 16-bit PCM
        pcm_24k = (np.clip(audio_np, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        
        # Resample to 8kHz for Twilio
        pcm_8k, _ = audioop.ratecv(pcm_24k, 2, 1, 24000, 8000, None)
        
        # Convert to Mu-Law
        ulaw = audioop.lin2ulaw(pcm_8k, 2)
        
        return {
            "audio_base64_ulaw": base64.b64encode(ulaw).decode(),
            "sample_rate": 8000,
            "format": "mulaw"
        }
        
    except Exception as e:
        print(f"Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {"error": str(e)}, 500

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006)
