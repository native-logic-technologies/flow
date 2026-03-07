#!/usr/bin/env python3
"""
ONNX Audio Decoder for MOSS-TTS -> Twilio 8kHz Mu-Law
Converts llama.cpp token output to Twilio-ready audio
"""

import onnxruntime as ort
import numpy as np
import audioop
import base64
from fastapi import FastAPI, Request
import os

app = FastAPI(title="MOSS-TTS ONNX Decoder (Twilio-Ready)")

# ONNX model path
ONNX_MODEL_PATH = "/home/phil/telephony-stack/models/tts-gguf/onnx_tokenizer/decoder.onnx"

print("Loading MOSS ONNX Decoder...", flush=True)
print(f"Model: {ONNX_MODEL_PATH}", flush=True)

# Load ONNX session with CUDA if available, else CPU
providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
session = ort.InferenceSession(ONNX_MODEL_PATH, providers=providers)
print(f"ONNX Providers: {session.get_providers()}", flush=True)
print("✅ Decoder ready!", flush=True)

@app.get("/health")
async def health():
    return {"status": "ok", "mode": "onnx_decoder_twilio", "model": "MOSS-Audio-Tokenizer-ONNX"}

@app.post("/decode")
async def decode_tokens(request: Request):
    """
    Decode MOSS-TTS tokens to Twilio-ready 8kHz Mu-Law audio.
    
    Input: {"tokens": [[85, 32], [86, 33], ...]}  # [Time, Quantizers]
    Output: {"audio_base64_ulaw": "..."}  # 8kHz Mu-Law base64
    """
    try:
        data = await request.json()
        
        # 1. Get tokens from llama.cpp
        # Tokens shape: [Time, Quantizers] typically [85, 32]
        tokens = np.array(data["tokens"], dtype=np.int64)
        
        # Ensure correct shape [batch, time, quantizers]
        if tokens.ndim == 2:
            tokens = np.expand_dims(tokens, axis=0)  # Add batch dim
        
        print(f"Decoding tokens shape: {tokens.shape}", flush=True)
        
        # 2. Run ONNX model -> Outputs Float32 audio at 24,000 Hz
        # ONNX input name is typically "tokens" or "audio_codes"
        input_name = session.get_inputs()[0].name
        wav_output = session.run(None, {input_name: tokens})[0]
        
        # 3. Convert Float32 to 16-bit PCM
        # Clamp to [-1, 1] to prevent clipping/static
        wav_output = np.clip(wav_output, -1.0, 1.0)
        pcm_16_24k = (wav_output * 32767.0).astype(np.int16).tobytes()
        
        # 4. Resample: 24kHz -> 8kHz (Twilio Standard)
        # audioop.ratecv(data, width, channels, in_rate, out_rate, state)
        pcm_16_8k, _ = audioop.ratecv(pcm_16_24k, 2, 1, 24000, 8000, None)
        
        # 5. Convert: 16-bit PCM -> 8-bit Mu-Law (Twilio Standard)
        mu_law_bytes = audioop.lin2ulaw(pcm_16_8k, 2)
        
        # 6. Base64 encode for Twilio Media Stream JSON payload
        payload = base64.b64encode(mu_law_bytes).decode('utf-8')
        
        return {
            "audio_base64_ulaw": payload,
            "sample_rate": 8000,
            "format": "mulaw",
            "input_tokens": tokens.shape[1] if tokens.ndim >= 2 else tokens.shape[0]
        }
        
    except Exception as e:
        print(f"Error decoding: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {"error": str(e)}, 500

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
