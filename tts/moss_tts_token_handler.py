#!/usr/bin/env python3
"""
MOSS-TTS Token-Level Streaming Handler
Receives individual tokens/chunks from Rust orchestrator and generates audio incrementally.

This enables true waterfall streaming:
- LLM generates token N at time T
- TTS receives and processes token N immediately
- While LLM generates token N+1, TTS generates audio for token N
"""

import asyncio
import json
import torch
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect


class TokenStreamingSession:
    """
    MOSS-TTS session optimized for token-level streaming from orchestrator.
    """
    
    def __init__(self, inferencer, processor, codec, tokenizer, device, 
                 voice_tokens=None, temperature=0.8, top_p=0.6, top_k=30):
        self.inferencer = inferencer
        self.processor = processor
        self.codec = codec
        self.tokenizer = tokenizer
        self.device = device
        
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        
        # Voice prompt (cached)
        self.voice_tokens = voice_tokens  # Shape: (85, 32)
        
        # Accumulated tokens for generation
        self.text_buffer = ""
        self.all_tokens = []
        self.generated_frames = []
        
        # Decoder for streaming audio
        self.decoder = None
        self.first_audio_sent = False
        
    def reset_with_voice(self, voice_tokens):
        """Reset session with voice prompt."""
        self.voice_tokens = voice_tokens
        self.text_buffer = ""
        self.all_tokens = []
        self.generated_frames = []
        self.decoder = None
        self.first_audio_sent = False
        
    def push_tokens(self, text_chunk: str):
        """
        Push new text tokens and generate audio frames incrementally.
        Returns list of audio frames (PCM bytes) ready to send.
        """
        if not text_chunk:
            return []
            
        self.text_buffer += text_chunk
        
        # Tokenize the new text
        new_tokens = self.tokenizer.encode(text_chunk, add_special_tokens=False)
        self.all_tokens.extend(new_tokens)
        
        # Initialize decoder on first tokens
        if self.decoder is None and self.voice_tokens is not None:
            from .moss_tts_streaming_handler import StreamingAudioDecoder
            self.decoder = StreamingAudioDecoder(self.codec, device=self.device)
            # Warm up with voice tokens
            self.decoder.push_tokens(self.voice_tokens)
        
        # Generate audio frames (limited quantity for streaming)
        if len(self.all_tokens) >= 3:  # Minimum context for coherent audio
            frames = self._generate_frames_streaming()
            
            # Decode to audio
            audio_chunks = []
            for frame in frames:
                if self.decoder:
                    self.decoder.push_tokens(frame)
                    for wav in self.decoder.audio_chunks():
                        pcm = self._tensor_to_pcm(wav)
                        audio_chunks.append(pcm)
                        self.first_audio_sent = True
                        
            return audio_chunks
        
        return []
    
    def _generate_frames_streaming(self, max_new_frames: int = 3):
        """
        Generate a small number of frames for low-latency streaming.
        """
        if not self.all_tokens:
            return []
            
        text_tokens = torch.tensor([self.all_tokens], device=self.device)
        
        # Prepare voice conditioning
        if self.voice_tokens is not None:
            # voice_tokens shape: (85, 32)
            voice_condition = self.voice_tokens.unsqueeze(0).to(self.device)
        else:
            voice_condition = None
        
        # Generate frames incrementally
        try:
            with torch.no_grad():
                # Use model's generate method with limited max_new_tokens
                # This is model-specific; adjust based on actual MOSS-TTS API
                frames = self.inferencer.generate_streaming(
                    text_tokens,
                    voice_condition=voice_condition,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    top_k=self.top_k,
                    max_new_frames=max_new_frames
                )
                return frames
        except Exception as e:
            print(f"[TokenHandler] Generation error: {e}")
            return []
    
    def finalize(self):
        """
        Finalize generation and return remaining audio.
        """
        if self.decoder is None:
            return []
            
        # Generate any remaining frames
        frames = self._generate_frames_streaming(max_new_frames=20)
        
        audio_chunks = []
        for frame in frames:
            self.decoder.push_tokens(frame)
            for wav in self.decoder.audio_chunks():
                pcm = self._tensor_to_pcm(wav)
                audio_chunks.append(pcm)
        
        # Flush decoder
        for wav in self.decoder.flush():
            pcm = self._tensor_to_pcm(wav)
            audio_chunks.append(pcm)
            
        return audio_chunks
    
    def _tensor_to_pcm(self, wav: torch.Tensor) -> bytes:
        """Convert audio tensor to PCM bytes."""
        wav = wav.squeeze().cpu().numpy()
        wav = np.clip(wav, -1.0, 1.0)
        wav_int16 = (wav * 32767).astype(np.int16)
        return wav_int16.tobytes()


async def handle_token_streaming_tts(websocket: WebSocket, model_components):
    """
    WebSocket handler for token-level streaming TTS.
    Protocol:
    - Client -> Server: {"type": "init", "voice": "name"}
    - Client -> Server: {"type": "token", "text": "partial text"}
    - Client -> Server: {"type": "end"}
    - Server -> Client: Binary PCM audio chunks
    - Server -> Client: {"type": "complete"}
    """
    
    inferencer = model_components['inferencer']
    processor = model_components['processor']
    codec = model_components['codec']
    tokenizer = model_components['tokenizer']
    device = model_components['device']
    
    await websocket.accept()
    print("[TokenHandler] WebSocket connected")
    
    session = None
    audio_queue = asyncio.Queue()
    text_queue = asyncio.Queue()
    generation_active = True
    
    async def text_receiver():
        """Receive text tokens from orchestrator."""
        nonlocal generation_active
        try:
            while True:
                msg = await websocket.receive_text()
                data = json.loads(msg)
                msg_type = data.get("type")
                
                if msg_type == "init":
                    # Initialize session with voice
                    voice_name = data.get("voice", "phil")
                    cached_voice = model_components.get('cached_voice_tokens')
                    
                    session = TokenStreamingSession(
                        inferencer, processor, codec, tokenizer, device,
                        voice_tokens=cached_voice
                    )
                    if cached_voice is not None:
                        session.reset_with_voice(cached_voice)
                    print(f"[TokenHandler] Session initialized with voice: {voice_name}")
                    
                elif msg_type == "token":
                    text = data.get("text", "")
                    if text:
                        await text_queue.put(text)
                        print(f"[TokenHandler] Received token chunk: '{text}'")
                        
                elif msg_type == "end":
                    print("[TokenHandler] Received end signal")
                    await text_queue.put("[END]")
                    break
                    
        except WebSocketDisconnect:
            print("[TokenHandler] Client disconnected")
            generation_active = False
        except Exception as e:
            print(f"[TokenHandler] Receiver error: {e}")
            generation_active = False
    
    async def audio_generator():
        """Generate audio from text tokens."""
        nonlocal session
        
        # Wait for session initialization
        while session is None and generation_active:
            await asyncio.sleep(0.01)
        
        if not generation_active:
            return
            
        accumulated = ""
        text_finished = False
        
        while generation_active:
            # Get new text with timeout for streaming
            try:
                chunk = await asyncio.wait_for(text_queue.get(), timeout=0.05)
                if chunk == "[END]":
                    text_finished = True
                else:
                    accumulated += chunk
                    print(f"[TokenHandler] Accumulated: '{accumulated}'")
            except asyncio.TimeoutError:
                pass
            
            # Process accumulated text if we have enough or text is finished
            if accumulated and (text_finished or len(accumulated) >= 3):
                text_to_process = accumulated
                accumulated = ""
                
                print(f"[TokenHandler] Generating audio for: '{text_to_process}'")
                audio_chunks = session.push_tokens(text_to_process)
                
                for pcm in audio_chunks:
                    await audio_queue.put(pcm)
                    print(f"[TokenHandler] Generated audio chunk: {len(pcm)} bytes")
            
            # Finalize if done
            if text_finished and not accumulated:
                print("[TokenHandler] Finalizing generation")
                final_chunks = session.finalize()
                for pcm in final_chunks:
                    await audio_queue.put(pcm)
                await audio_queue.put("[DONE]")
                break
    
    async def audio_sender():
        """Send audio chunks back to orchestrator."""
        try:
            while generation_active:
                chunk = await audio_queue.get()
                
                if chunk == "[DONE]":
                    await websocket.send_text(json.dumps({"type": "complete"}))
                    print("[TokenHandler] Sent completion signal")
                    break
                
                await websocket.send_bytes(chunk)
                print(f"[TokenHandler] Sent audio: {len(chunk)} bytes")
                
        except Exception as e:
            print(f"[TokenHandler] Sender error: {e}")
    
    # Run all three tasks
    try:
        await asyncio.gather(
            text_receiver(),
            audio_generator(),
            audio_sender(),
            return_exceptions=True
        )
    except Exception as e:
        print(f"[TokenHandler] Handler error: {e}")
    finally:
        print("[TokenHandler] Handler ended")
