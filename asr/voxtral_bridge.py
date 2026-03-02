#!/usr/bin/env python3
"""
Voxtral Bridge Server
Converts HTTP PCM audio requests to vLLM Realtime API WebSocket format
Port: 8001 (HTTP) -> forwards to vLLM WebSocket
"""

import asyncio
import json
import numpy as np
import websockets
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Voxtral Bridge", version="1.0")

VLLM_WS_URL = "ws://localhost:8002/v1/realtime"  # vLLM realtime WebSocket


@app.post("/v1/audio/transcriptions")
async def transcribe_audio(request: Request):
    """
    Receive PCM audio and transcribe using Voxtral via vLLM Realtime API
    """
    start_time = asyncio.get_event_loop().time()
    
    try:
        # Get PCM bytes
        pcm_bytes = await request.body()
        if len(pcm_bytes) == 0:
            return JSONResponse({"text": ""})
        
        # Convert to float32 array
        audio_array = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Convert to base64 for WebSocket transmission
        import base64
        audio_b64 = base64.b64encode(audio_array.tobytes()).decode('utf-8')
        
        # Connect to vLLM Realtime API
        transcript = await transcribe_with_vllm(audio_b64)
        
        elapsed = (asyncio.get_event_loop().time() - start_time) * 1000
        logger.info(f"Transcribed in {elapsed:.1f}ms: '{transcript[:50]}...' " if len(transcript) > 50 else f"Transcribed in {elapsed:.1f}ms: '{transcript}'")
        
        return {"text": transcript}
        
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def transcribe_with_vllm(audio_b64: str) -> str:
    """
    Connect to vLLM Realtime API via WebSocket and get transcription
    """
    try:
        async with websockets.connect(VLLM_WS_URL) as ws:
            # Send audio data
            request_msg = {
                "type": "audio",
                "audio": audio_b64,
                "format": "pcm_f32le",
                "sample_rate": 16000
            }
            await ws.send(json.dumps(request_msg))
            
            # Wait for response
            response = await ws.recv()
            data = json.loads(response)
            
            if "text" in data:
                return data["text"]
            elif "delta" in data:
                return data["delta"]
            else:
                return ""
                
    except Exception as e:
        logger.error(f"vLLM WebSocket error: {e}")
        # Fallback: return empty if vLLM is not ready
        return ""


@app.get("/health")
async def health():
    return {"status": "ok", "service": "voxtral-bridge"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
