"""
True Streaming TTS Handler for MOSS-TTS-Realtime
=================================================
Implements token-level streaming with async queues.

Architecture:
- Text tokens arrive from LLM via WebSocket
- Each token is immediately pushed to MOSS-TTS session
- Audio chunks are streamed back as they're generated
- Parallel processing: LLM generates while TTS speaks
"""

import asyncio
import json
import numpy as np
import torch
from fastapi import WebSocket, WebSocketDisconnect


async def handle_streaming_tts(websocket: WebSocket, model_components):
    """
    True streaming TTS WebSocket handler.
    
    Protocol:
    1. Client sends: {"type": "init", "voice": "phil"} - Initialize session
    2. Client streams tokens: {"type": "token", "text": "Hello"}
    3. Client sends: {"type": "end"} - Signal end of text
    4. Server streams audio chunks back immediately via binary messages
    """
    inferencer = model_components['inferencer']
    processor = model_components['processor']
    codec = model_components['codec']
    tokenizer = model_components['tokenizer']
    device = model_components['device']
    cached_voice_tokens = model_components.get('cached_voice_tokens')
    
    from mossttsrealtime.streaming_mossttsrealtime import (
        MossTTSRealtimeStreamingSession,
        AudioStreamDecoder
    )
    from moss_tts_fastapi_server import tensor_to_pcm_bytes, CODEC_SAMPLE_RATE
    
    await websocket.accept()
    print("DEBUG: Streaming TTS connection accepted", flush=True)
    
    # Async queues for inter-thread communication
    text_queue = asyncio.Queue()  # Incoming text from client
    audio_queue = asyncio.Queue()  # Generated audio to send
    
    # Session state
    session = None
    decoder = None
    
    try:
        # Wait for init message
        init_msg = await websocket.receive_text()
        init_data = json.loads(init_msg)
        
        if init_data.get("type") != "init":
            await websocket.send_text(json.dumps({"error": "Expected init message"}))
            await websocket.close()
            return
        
        # Initialize MOSS-TTS streaming session
        print("DEBUG: Initializing MOSS streaming session...", flush=True)
        session = MossTTSRealtimeStreamingSession(
            inferencer,
            processor,
            codec=codec,
            codec_sample_rate=CODEC_SAMPLE_RATE,
            codec_encode_kwargs={"chunk_duration": 8},
            prefill_text_len=3,  # Low latency: generate audio after 3 tokens (was 12)
            temperature=0.8,
            top_p=0.6,
            top_k=30,
            do_sample=True,
            repetition_penalty=1.1,
            repetition_window=50,
        )
        
        # Set cached voice embedding
        if cached_voice_tokens is not None:
            session.set_voice_prompt_tokens(cached_voice_tokens)
            print(f"DEBUG: Using cached voice: {cached_voice_tokens.shape}", flush=True)
        else:
            session.clear_voice_prompt()
            print("DEBUG: No cached voice, using default", flush=True)
        
        # Build system prompt with voice
        system_prompt = processor.make_ensemble(cached_voice_tokens)
        assistant_prefix = "<|im_end|>\n<|im_start|>assistant\n"
        assistant_prefix_ids = tokenizer.encode(assistant_prefix, add_special_tokens=False)
        
        # Create assistant prefix with audio channels
        assistant_prefix_array = np.full(
            (len(assistant_prefix_ids), system_prompt.shape[1]),
            fill_value=processor.audio_channel_pad,
            dtype=np.int64,
        )
        assistant_prefix_array[:, 0] = assistant_prefix_ids
        
        # Combine: system prompt + assistant prefix
        input_ids = np.concatenate([system_prompt, assistant_prefix_array], axis=0)
        
        # Reset turn with system prompt
        session.reset_turn(input_ids=input_ids, include_system_prompt=False, reset_cache=True)
        
        # Create audio decoder
        decoder = AudioStreamDecoder(
            codec,
            chunk_frames=3,  # Small chunks for low latency
            overlap_frames=0,
            decode_kwargs={"chunk_duration": -1},
            device=device,
        )
        
        codebook_size = int(getattr(codec, "codebook_size", 1024))
        audio_eos_token = int(getattr(inferencer, "audio_eos_token", 1026))
        
        print("DEBUG: Session ready, starting streams...", flush=True)
        
        # TASK 1: Text Listener - Receives tokens from client
        async def text_listener():
            """Listen for incoming text tokens and queue them."""
            try:
                print("DEBUG: Text listener started", flush=True)
                while True:
                    msg = await websocket.receive_text()
                    print(f"DEBUG: Text listener received: {msg[:50]}...", flush=True)
                    data = json.loads(msg)
                    msg_type = data.get("type")
                    
                    if msg_type == "token":
                        text = data.get("text", "")
                        if text:
                            await text_queue.put(text)
                            print(f"DEBUG: Queued token: '{text}'", flush=True)
                    
                    elif msg_type == "end":
                        await text_queue.put("[END]")
                        print("DEBUG: Received END signal", flush=True)
                        break
                    
                    elif msg_type == "text":
                        # Legacy: full text in one message
                        text = data.get("text", "")
                        if text:
                            print(f"DEBUG: Queued full text: '{text[:30]}...'", flush=True)
                            await text_queue.put(text)
                            await text_queue.put("[END]")
                            break
                            
            except WebSocketDisconnect:
                print("DEBUG: Text listener: Client disconnected", flush=True)
                await text_queue.put("[END]")
            except Exception as e:
                print(f"DEBUG: Text listener error: {e}", flush=True)
                import traceback
                traceback.print_exc()
                await text_queue.put("[END]")
        
        # TASK 2: Audio Generator - Processes text and generates audio
        async def audio_generator():
            """Generate audio from text tokens and queue for sending."""
            try:
                print("DEBUG: Audio generator started", flush=True)
                accumulated_text = ""
                text_finished = False
                audio_chunks_generated = 0
                
                with codec.streaming(batch_size=1):
                    while not text_finished or accumulated_text:
                        # Check for new text
                        try:
                            text_chunk = await asyncio.wait_for(text_queue.get(), timeout=0.05)
                            if text_chunk == "[END]":
                                print(f"DEBUG: Audio generator got END signal", flush=True)
                                text_finished = True
                            else:
                                accumulated_text += text_chunk
                                print(f"DEBUG: Audio generator got text: '{text_chunk}', accumulated: '{accumulated_text}'", flush=True)
                        except asyncio.TimeoutError:
                            pass
                        
                        audio_frames = []
                        
                        # If we have text and haven't processed it yet
                        if accumulated_text and (text_finished or len(accumulated_text) > 3):
                            text = accumulated_text
                            accumulated_text = ""
                            
                            print(f"DEBUG: Processing text: '{text}'", flush=True)
                            
                            # Tokenize
                            text_tokens = tokenizer.encode(text, add_special_tokens=False)
                            print(f"DEBUG: Tokenized to {len(text_tokens)} tokens", flush=True)
                            
                            if text_tokens:
                                # Push to MOSS-TTS session (in thread to avoid blocking)
                                print(f"DEBUG: Pushing {len(text_tokens)} tokens to session", flush=True)
                                frames = await asyncio.get_event_loop().run_in_executor(
                                    None, lambda: session.push_text_tokens(text_tokens)
                                )
                                print(f"DEBUG: Got {len(frames)} audio frames from push_text_tokens", flush=True)
                                audio_frames.extend(frames)
                        
                        # If text is finished, call end_text() to trigger generation
                        if text_finished and accumulated_text == "":
                            print(f"DEBUG: Calling end_text() to trigger generation", flush=True)
                            # Run in thread to avoid blocking event loop
                            end_frames = await asyncio.get_event_loop().run_in_executor(
                                None, session.end_text
                            )
                            print(f"DEBUG: Got {len(end_frames)} audio frames from end_text", flush=True)
                            audio_frames.extend(end_frames)
                        
                        # Process all audio frames
                        for frame in audio_frames:
                            if frame is None or frame.numel() == 0:
                                continue
                            
                            # Handle shape
                            if frame.dim() == 3:
                                frame = frame[0]
                            
                            # Check for EOS
                            eos_rows = (frame[:, 0] == audio_eos_token).nonzero(as_tuple=False)
                            invalid_rows = ((frame < 0) | (frame >= codebook_size)).any(dim=1)
                            
                            if eos_rows.numel() > 0 or invalid_rows.any():
                                continue
                            
                            # Decode audio
                            decoder.push_tokens(frame.detach())
                            
                            # Get audio chunks
                            for wav in decoder.audio_chunks():
                                if wav.numel() == 0:
                                    continue
                                
                                pcm_bytes = tensor_to_pcm_bytes(wav)
                                if pcm_bytes:
                                    await audio_queue.put(pcm_bytes)
                                    audio_chunks_generated += 1
                        
                        # If text is finished, drain remaining
                        if text_finished and not accumulated_text:
                            print(f"DEBUG: Draining remaining audio", flush=True)
                            remaining_frames = await asyncio.get_event_loop().run_in_executor(
                                None, lambda: session.drain(max_steps=10)
                            )
                            print(f"DEBUG: Got {len(remaining_frames)} frames from drain", flush=True)
                            
                            for frame in remaining_frames:
                                if frame is None or frame.numel() == 0:
                                    continue
                                
                                if frame.dim() == 3:
                                    frame = frame[0]
                                
                                eos_rows = (frame[:, 0] == audio_eos_token).nonzero(as_tuple=False)
                                invalid_rows = ((frame < 0) | (frame >= codebook_size)).any(dim=1)
                                
                                if eos_rows.numel() > 0 or invalid_rows.any():
                                    continue
                                
                                decoder.push_tokens(frame.detach())
                                
                                for wav in decoder.audio_chunks():
                                    if wav.numel() == 0:
                                        continue
                                    pcm_bytes = tensor_to_pcm_bytes(wav)
                                    if pcm_bytes:
                                        await audio_queue.put(pcm_bytes)
                                        audio_chunks_generated += 1
                            
                            break
                
                # Flush final chunk
                final_chunk = decoder.flush()
                if final_chunk is not None and final_chunk.numel() > 0:
                    pcm_bytes = tensor_to_pcm_bytes(final_chunk)
                    if pcm_bytes:
                        await audio_queue.put(pcm_bytes)
                        audio_chunks_generated += 1
                
                print(f"DEBUG: Audio generator complete: {audio_chunks_generated} chunks", flush=True)
                await audio_queue.put("[DONE]")
                
            except Exception as e:
                print(f"DEBUG: Audio generator error: {e}", flush=True)
                import traceback
                traceback.print_exc()
                await audio_queue.put("[DONE]")
        
        # TASK 3: Audio Sender - Sends audio chunks back to client
        async def audio_sender():
            """Send audio chunks from queue back to client."""
            chunks_sent = 0
            try:
                while True:
                    chunk = await audio_queue.get()
                    
                    if chunk == "[DONE]":
                        break
                    
                    await websocket.send_bytes(chunk)
                    chunks_sent += 1
                
                # Send completion signal
                await websocket.send_text(json.dumps({"type": "complete", "done": True}))
                print(f"DEBUG: Audio sender complete: {chunks_sent} chunks sent", flush=True)
                
            except WebSocketDisconnect:
                print(f"DEBUG: Audio sender: Client disconnected after {chunks_sent} chunks", flush=True)
            except Exception as e:
                print(f"DEBUG: Audio sender error: {e}", flush=True)
        
        # Start all tasks in parallel
        print("DEBUG: Starting parallel tasks...", flush=True)
        await asyncio.gather(
            text_listener(),
            audio_generator(),
            audio_sender(),
            return_exceptions=True
        )
        
    except WebSocketDisconnect:
        print("DEBUG: WebSocket disconnected", flush=True)
    except Exception as e:
        print(f"DEBUG: WebSocket handler error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        print("DEBUG: WebSocket handler complete", flush=True)
        try:
            await websocket.close()
        except:
            pass
