#!/usr/bin/env python3
"""
MOSS-TTS-Realtime FastAPI Server
Native PyTorch implementation with OpenAI-compatible API

CRITICAL: Uses StreamingResponse for real-time audio streaming (20ms chunks)
"""

import os
import sys
import io
import json
import base64
import asyncio
import torch
import torchaudio
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

# Add MOSS-TTS source to path
# The mossttsrealtime package is in moss_tts_realtime subdirectory
sys.path.insert(0, os.path.expanduser("~/telephony-stack/moss-tts-src/moss_tts_realtime"))
sys.path.insert(0, os.path.expanduser("~/telephony-stack/moss-tts-src"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

# Global instances
model = None
tokenizer = None
codec = None
processor = None
inferencer = None

device = "cuda" if torch.cuda.is_available() else "cpu"
CODEC_SAMPLE_RATE = 24000


class TTSRequest(BaseModel):
    """OpenAI-compatible TTS request with MOSS-specific extensions"""
    model: str = "OpenMOSS-Team/MOSS-TTS-Realtime"
    input: str = Field(..., description="Text to synthesize")
    voice: str = "default"
    response_format: str = "pcm"  # pcm, wav, mp3
    speed: float = Field(1.0, ge=0.5, le=2.0)
    
    # MOSS-specific generation parameters
    temperature: float = Field(0.8, ge=0.0, le=2.0)
    top_p: float = Field(0.6, ge=0.0, le=1.0)
    top_k: int = Field(30, ge=1, le=100)
    repetition_penalty: float = Field(1.1, ge=1.0, le=2.0)
    
    # Zero-shot voice cloning via extra_body (LiveKit compatibility)
    extra_body: Optional[Dict[str, Any]] = Field(None, description="Extra parameters including reference_audio for voice cloning")


@dataclass
class StreamingConfig:
    """Configuration for streaming TTS generation"""
    text_chunk_tokens: int = 12
    decode_chunk_frames: int = 12
    decode_overlap_frames: int = 0
    chunk_duration: float = 0.24
    prebuffer_seconds: float = 0.0


def load_models():
    """Load MOSS-TTS model, tokenizer, and codec"""
    global model, tokenizer, codec, processor, inferencer
    
    from transformers import AutoTokenizer, AutoModel
    from mossttsrealtime import MossTTSRealtime, MossTTSRealtimeProcessor
    from mossttsrealtime.streaming_mossttsrealtime import MossTTSRealtimeInference as StreamingMossTTSInference
    
    model_path = os.path.expanduser("~/telephony-stack/models/tts/moss-tts-realtime")
    # Use LOCAL codec path (patched for transformers 4.x compatibility)
    codec_path = os.path.expanduser("~/telephony-stack/models/tts/moss-audio-tokenizer")
    
    print(f"Loading MOSS-TTS from {model_path}...")
    print(f"Device: {device}")
    
    # Determine dtype and attention implementation
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    attn_implementation = "sdpa"  # Use SDPA for compatibility
    
    print(f"Dtype: {dtype}, Attention: {attn_implementation}")
    
    # Load model
    model = MossTTSRealtime.from_pretrained(
        model_path,
        attn_implementation=attn_implementation,
        torch_dtype=dtype,
        trust_remote_code=True
    ).to(device)
    model.eval()
    
    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    
    # Load processor
    processor = MossTTSRealtimeProcessor(tokenizer)
    
    # Load codec from LOCAL path (patched version)
    print(f"Loading codec from local path: {codec_path}...")
    codec = AutoModel.from_pretrained(codec_path, trust_remote_code=True, local_files_only=True).eval()
    codec = codec.to(device)
    
    # Create streaming inferencer (different from non-streaming version)
    global inferencer
    inferencer = StreamingMossTTSInference(model, tokenizer, max_length=2048)
    inferencer.reset_generation_state(keep_cache=False)
    
    print("✓ MOSS-TTS-Realtime ready!")
    print(f"  - Sample rate: {CODEC_SAMPLE_RATE} Hz")
    print(f"  - Max length: 2048 tokens")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models on startup"""
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  MOSS-TTS-Realtime FastAPI Server                                  ║")
    print("║  Port: 8002                                                        ║")
    print("║  Mode: Native PyTorch (vLLM incompatible)                          ║")
    print("║  Feature: Real-time streaming (20ms chunks)                        ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    
    load_models()
    yield
    
    # Cleanup
    print("Shutting down MOSS-TTS server...")


app = FastAPI(
    title="MOSS-TTS-Realtime API",
    description="OpenAI-compatible TTS API for MOSS-TTS-Realtime with streaming support",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
        "device": device,
        "sample_rate": CODEC_SAMPLE_RATE,
        "mode": "native_pytorch_streaming"
    }


@app.get("/v1/models")
async def list_models():
    """List available models (OpenAI-compatible)"""
    return {
        "object": "list",
        "data": [
            {
                "id": "OpenMOSS-Team/MOSS-TTS-Realtime",
                "object": "model",
                "created": 0,
                "owned_by": "OpenMOSS"
            }
        ]
    }


def encode_reference_audio(audio_path_or_bytes, codec, device):
    """Encode reference audio to tokens for voice cloning"""
    if isinstance(audio_path_or_bytes, str):
        # Load from file path
        wav, sr = torchaudio.load(audio_path_or_bytes)
    else:
        # Load from bytes
        buffer = io.BytesIO(audio_path_or_bytes)
        wav, sr = torchaudio.load(buffer)
    
    if sr != CODEC_SAMPLE_RATE:
        wav = torchaudio.functional.resample(wav, sr, CODEC_SAMPLE_RATE)
    if wav.ndim == 2 and wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    
    waveform = wav.unsqueeze(0).to(device)
    
    with torch.no_grad():
        encode_result = codec.encode(waveform, chunk_duration=8)
        
    # Extract codes from result
    if isinstance(encode_result, dict):
        codes = encode_result["audio_codes"]
    elif hasattr(encode_result, "audio_codes"):
        codes = encode_result.audio_codes
    else:
        codes = encode_result
        
    if isinstance(codes, np.ndarray):
        codes = torch.from_numpy(codes)
    
    # Reshape to expected format
    if codes.dim() == 3:
        if codes.shape[1] == 1:
            codes = codes[:, 0, :]
        elif codes.shape[0] == 1:
            codes = codes[0]
            
    return codes.detach().cpu().numpy()


async def generate_audio_stream(
    text: str,
    reference_audio: Optional[bytes] = None,
    temperature: float = 0.8,
    top_p: float = 0.6,
    top_k: int = 30,
    repetition_penalty: float = 1.1,
) -> AsyncGenerator[bytes, None]:
    """
    Stream audio chunks in real-time (20ms chunks).
    Yields raw PCM bytes as they're generated.
    """
    from mossttsrealtime.streaming_mossttsrealtime import (
        MossTTSRealtimeStreamingSession,
        AudioStreamDecoder
    )
    
    # Encode reference audio if provided (zero-shot voice cloning)
    prompt_tokens = None
    if reference_audio is not None:
        try:
            prompt_codes = encode_reference_audio(reference_audio, codec, device)
            prompt_tokens = prompt_codes.squeeze(1) if prompt_codes.ndim == 3 else prompt_codes
        except Exception as e:
            print(f"Warning: Failed to encode reference audio: {e}")
            prompt_tokens = None
    
    # Create streaming session
    session = MossTTSRealtimeStreamingSession(
        inferencer,
        processor,
        codec=codec,
        codec_sample_rate=CODEC_SAMPLE_RATE,
        codec_encode_kwargs={"chunk_duration": 8},
        prefill_text_len=processor.delay_tokens_len,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        do_sample=True,
        repetition_penalty=repetition_penalty,
        repetition_window=50,
    )
    
    # Set voice prompt
    if prompt_tokens is not None:
        session.set_voice_prompt_tokens(prompt_tokens)
    else:
        session.clear_voice_prompt()
    
    # Build turn input
    turn_input = processor.make_ensemble(prompt_tokens)
    user_text = "Hello!"  # Default user text
    user_prompt_text = f"<|im_end|>\n<|im_start|>user\n{user_text}<|im_end|>\n<|im_start|>assistant\n"
    user_prompt_tokens = tokenizer(user_prompt_text)["input_ids"]
    user_prompt = np.full(
        shape=(len(user_prompt_tokens), processor.channels + 1),
        fill_value=processor.audio_channel_pad,
        dtype=np.int64,
    )
    user_prompt[:, 0] = np.asarray(user_prompt_tokens, dtype=np.int64)
    turn_input = np.concatenate([turn_input, user_prompt], axis=0)
    
    session.reset_turn(input_ids=turn_input, include_system_prompt=True, reset_cache=True)
    
    # Create audio decoder
    decoder = AudioStreamDecoder(
        codec,
        chunk_frames=12,
        overlap_frames=0,
        decode_kwargs={"chunk_duration": -1},
        device=device,
    )
    
    # Tokenize text
    text_tokens = tokenizer.encode(text, add_special_tokens=False)
    
    # Stream configuration
    text_chunk_size = 12
    codebook_size = int(getattr(codec, "codebook_size", 1024))
    audio_eos_token = int(getattr(inferencer, "audio_eos_token", 1026))
    
    chunk_index = 0
    
    def sanitize_tokens(tokens):
        """Remove invalid tokens and EOS"""
        if tokens.dim() == 1:
            tokens = tokens.unsqueeze(0)
        if tokens.numel() == 0:
            return tokens, False
        eos_rows = (tokens[:, 0] == audio_eos_token).nonzero(as_tuple=False)
        invalid_rows = ((tokens < 0) | (tokens >= codebook_size)).any(dim=1)
        stop_idx = None
        if eos_rows.numel() > 0:
            stop_idx = int(eos_rows[0].item())
        if invalid_rows.any():
            invalid_idx = int(invalid_rows.nonzero(as_tuple=False)[0].item())
            stop_idx = invalid_idx if stop_idx is None else min(stop_idx, invalid_idx)
        if stop_idx is not None:
            tokens = tokens[:stop_idx]
            return tokens, True
        return tokens, False
    
    with codec.streaming(batch_size=1):
        # Process text in chunks
        for i in range(0, len(text_tokens), text_chunk_size):
            chunk = text_tokens[i:i + text_chunk_size]
            
            # Generate audio frames for this text chunk
            audio_frames = session.push_text_tokens(chunk)
            
            for frame in audio_frames:
                tokens = frame
                if tokens.dim() == 3:
                    tokens = tokens[0]
                
                tokens, stopped = sanitize_tokens(tokens)
                if tokens.numel() == 0:
                    continue
                
                # Decode to audio
                decoder.push_tokens(tokens.detach())
                
                for wav in decoder.audio_chunks():
                    if wav.numel() == 0:
                        continue
                    
                    # Convert to PCM bytes and yield immediately
                    wav_np = wav.detach().cpu().numpy().reshape(-1)
                    pcm_bytes = (wav_np * 32767).astype(np.int16).tobytes()
                    yield pcm_bytes
                    chunk_index += 1
                
                if stopped:
                    break
            
            if session.inferencer.is_finished:
                break
        
        # Finalize
        final_frames = session.end_text()
        for frame in final_frames:
            tokens = frame
            if tokens.dim() == 3:
                tokens = tokens[0]
            tokens, _ = sanitize_tokens(tokens)
            if tokens.numel() == 0:
                continue
            
            decoder.push_tokens(tokens.detach())
            for wav in decoder.audio_chunks():
                if wav.numel() == 0:
                    continue
                wav_np = wav.detach().cpu().numpy().reshape(-1)
                pcm_bytes = (wav_np * 32767).astype(np.int16).tobytes()
                yield pcm_bytes
        
        # Flush remaining audio
        final_chunk = decoder.flush()
        if final_chunk is not None and final_chunk.numel() > 0:
            wav_np = final_chunk.detach().cpu().numpy().reshape(-1)
            pcm_bytes = (wav_np * 32767).astype(np.int16).tobytes()
            yield pcm_bytes


@app.post("/v1/audio/speech")
async def text_to_speech(request: TTSRequest):
    """
    OpenAI-compatible text-to-speech endpoint with real-time streaming.
    
    CRITICAL: Uses StreamingResponse to yield audio chunks (20ms) immediately
    as they're generated, rather than waiting for full generation.
    """
    if inferencer is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Extract reference audio from extra_body (zero-shot voice cloning)
        reference_audio = None
        if request.extra_body:
            ref_audio_b64 = request.extra_body.get("reference_audio")
            if ref_audio_b64:
                reference_audio = base64.b64decode(ref_audio_b64)
        
        # For non-streaming formats (wav, mp3), collect all audio first
        if request.response_format in ["wav", "mp3"]:
            chunks = []
            async for chunk in generate_audio_stream(
                text=request.input,
                reference_audio=reference_audio,
                temperature=request.temperature,
                top_p=request.top_p,
                top_k=request.top_k,
                repetition_penalty=request.repetition_penalty,
            ):
                chunks.append(chunk)
            
            # Combine all PCM chunks
            all_pcm = b"".join(chunks)
            wav_np = np.frombuffer(all_pcm, dtype=np.int16).astype(np.float32) / 32767.0
            wav_tensor = torch.from_numpy(wav_np).unsqueeze(0)
            
            # Encode to requested format
            buffer = io.BytesIO()
            if request.response_format == "wav":
                torchaudio.save(buffer, wav_tensor, CODEC_SAMPLE_RATE, format="wav")
                media_type = "audio/wav"
            else:  # mp3
                torchaudio.save(buffer, wav_tensor, CODEC_SAMPLE_RATE, format="mp3")
                media_type = "audio/mpeg"
            
            buffer.seek(0)
            return StreamingResponse(
                buffer,
                media_type=media_type,
                headers={
                    "X-Model": "MOSS-TTS-Realtime",
                    "X-Sample-Rate": str(CODEC_SAMPLE_RATE)
                }
            )
        
        # For PCM format, stream chunks in real-time (RECOMMENDED)
        else:
            async def pcm_generator():
                async for chunk in generate_audio_stream(
                    text=request.input,
                    reference_audio=reference_audio,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    top_k=request.top_k,
                    repetition_penalty=request.repetition_penalty,
                ):
                    yield chunk
            
            return StreamingResponse(
                pcm_generator(),
                media_type="audio/pcm",
                headers={
                    "X-Model": "MOSS-TTS-Realtime",
                    "X-Sample-Rate": str(CODEC_SAMPLE_RATE),
                    "X-Format": "s16le",  # Signed 16-bit little-endian
                    "X-Channels": "1"     # Mono
                }
            )
        
    except Exception as e:
        print(f"Error in TTS generation: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/chat/completions")
async def chat_completions():
    """Dummy endpoint for compatibility"""
    return {
        "id": "chatcmpl-moss-tts",
        "object": "chat.completion",
        "created": 0,
        "model": "MOSS-TTS-Realtime",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "This is a TTS model. Use POST /v1/audio/speech endpoint."
            },
            "finish_reason": "stop"
        }]
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
