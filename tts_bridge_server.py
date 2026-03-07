#!/usr/bin/env python3
"""
TTS Bridge: OpenAI-compatible /v1/audio/speech endpoint
Routes: llama.cpp (tokens) -> ONNX decoder (audio) -> Twilio-ready Mu-Law
"""

import os
import sys
import json
import base64
import httpx
import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import io

app = FastAPI(title="TTS Bridge - llama.cpp + ONNX")

# Service endpoints
LLAMA_TTS_URL = "http://localhost:8002/completion"
ONNX_DECODER_URL = "http://localhost:8005/decode"

# MOSS-TTS prompt template
TTS_SYSTEM_PROMPT = """<|im_start|>system
You are a text-to-speech engine. Convert the user's text to natural speech.<|im_end|>
<|im_start|>user
{text}<|im_end|>
<|im_start|>assistant
<|audio_start|>"""

@app.get("/health")
async def health():
    return {"status": "ok", "mode": "tts_bridge_llama_onnx"}

@app.post("/v1/audio/speech")
async def text_to_speech(request: Request):
    """
    OpenAI-compatible TTS endpoint.
    Flow: Text -> llama.cpp (tokens) -> ONNX (audio) -> Mu-Law PCM
    """
    try:
        data = await request.json()
        text = data.get("input", "")
        voice = data.get("voice", "default")
        
        print(f"TTS request: '{text[:50]}...' voice={voice}", flush=True)
        
        # Step 1: Generate tokens via llama.cpp
        prompt = TTS_SYSTEM_PROMPT.format(text=text)
        
        async with httpx.AsyncClient() as client:
            llama_response = await client.post(
                LLAMA_TTS_URL,
                json={
                    "prompt": prompt,
                    "n_predict": 200,
                    "temperature": 0.8,
                    "stop": ["<|audio_end|>", "<|im_end|>"]
                },
                timeout=30.0
            )
            llama_result = llama_response.json()
        
        # Extract generated tokens from completion
        # llama.cpp returns text, we need to parse/extract token IDs
        # For now, this is a simplified version - actual token extraction depends on model output format
        generated_text = llama_result.get("content", "")
        
        print(f"Generated text: {generated_text[:50]}...", flush=True)
        
        # Step 2: Convert to tokens and decode via ONNX
        # This is a placeholder - actual implementation needs proper token extraction
        # For MOSS-TTS, we need to extract the audio tokens from the model output
        
        # For now, return an error indicating the bridge needs token extraction logic
        return {
            "error": "TTS Bridge needs token extraction from llama.cpp output",
            "note": "llama.cpp returns text tokens, not audio tokens directly. Need to extract audio token IDs from model output.",
            "generated": generated_text[:100]
        }
        
    except Exception as e:
        print(f"TTS error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {"error": str(e)}, 500

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
