"""
Thread-safe WebSocket TTS handler for MOSS-TTS
Runs PyTorch generation in a separate thread to avoid blocking the async event loop
"""

import asyncio
import threading
import json
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect


async def handle_websocket_tts(websocket: WebSocket, model_components):
    """
    Thread-safe WebSocket handler for streaming TTS.
    
    Args:
        websocket: The FastAPI WebSocket connection
        model_components: Dict with 'inferencer', 'processor', 'codec', 'tokenizer', 'device'
    """
    inferencer = model_components['inferencer']
    processor = model_components['processor']
    codec = model_components['codec']
    tokenizer = model_components['tokenizer']
    device = model_components['device']
    
    from mossttsrealtime.streaming_mossttsrealtime import (
        MossTTSRealtimeStreamingSession,
        AudioStreamDecoder
    )
    
    await websocket.accept()
    print("DEBUG: WebSocket TTS connection accepted", flush=True)
    
    try:
        # Wait for init message
        init_msg = await websocket.receive_text()
        init_data = json.loads(init_msg)
        
        if init_data.get("type") != "init":
            await websocket.send_text(json.dumps({"error": "Expected init message with type 'init'"}))
            await websocket.close()
            return
        
        # Import from main server
        from moss_tts_fastapi_server import tensor_to_pcm_bytes, CODEC_SAMPLE_RATE, CACHED_VOICE_PROMPT_TOKENS
        
        # Use CACHED voice embedding for instant voice cloning (~600ms saved!)
        # If no cached embedding, fall back to default voice
        prompt_tokens = CACHED_VOICE_PROMPT_TOKENS
        
        if prompt_tokens is not None:
            print(f"DEBUG: WebSocket using CACHED voice embedding (fast!)", flush=True)
        else:
            print(f"DEBUG: No cached voice, using default TTS voice", flush=True)
        
        # Thread-safe queue to pass audio from PyTorch thread to async loop
        audio_queue = asyncio.Queue()
        text_queue = asyncio.Queue()  # For passing text from main thread to generator thread
        loop = asyncio.get_running_loop()
        
        # Create session (in main thread for now)
        session = MossTTSRealtimeStreamingSession(
            inferencer,
            processor,
            codec=codec,
            codec_sample_rate=CODEC_SAMPLE_RATE,
            codec_encode_kwargs={"chunk_duration": 8},
            prefill_text_len=processor.delay_tokens_len,
            temperature=0.8,
            top_p=0.6,
            top_k=30,
            do_sample=True,
            repetition_penalty=1.1,
            repetition_window=50,
        )
        
        if prompt_tokens is not None:
            session.set_voice_prompt_tokens(prompt_tokens)
        else:
            session.clear_voice_prompt()
        
        codebook_size = int(getattr(codec, "codebook_size", 1024))
        audio_eos_token = int(getattr(inferencer, "audio_eos_token", 1026))
        
        # State shared between threads
        state = {
            'text_buffer': "",
            'finished': False,
            'error': None
        }
        
        # The PyTorch Worker Thread
        def generate_audio_thread():
            try:
                print(f"DEBUG: Generator thread started", flush=True)
                
                # Create decoder in this thread
                decoder = AudioStreamDecoder(
                    codec,
                    chunk_frames=12,
                    overlap_frames=0,
                    decode_kwargs={"chunk_duration": -1},
                    device=device,
                )
                
                audio_chunks_sent = 0
                
                with codec.streaming(batch_size=1):
                    # For true streaming, we need to track what's been processed
                    accumulated_text = ""
                    processed = False
                    min_tokens_to_generate = 12  # MOSS needs ~12 tokens before generating audio
                    
                    while not state['finished'] or not processed:
                        # Check if there's new text to accumulate
                        if state['text_buffer']:
                            accumulated_text += state['text_buffer']
                            state['text_buffer'] = ""  # Clear buffer
                            # print(f"DEBUG: Accumulated text: '{accumulated_text[-30:]}...' ({len(accumulated_text)} chars)", flush=True)
                        
                        # Check if we have enough tokens to start generating
                        current_tokens = len(tokenizer.encode(accumulated_text, add_special_tokens=False))
                        
                        # Process when we have enough tokens OR when finished
                        if (current_tokens >= min_tokens_to_generate or state['finished']) and accumulated_text and not processed:
                            text = accumulated_text
                            processed = True
                            
                            print(f"DEBUG: Processing FINAL text: '{text[:50]}...' ({len(text)} chars)", flush=True)
                            
                            # Build user prompt
                            user_prompt_text = f"<|im_end|>\n<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"
                            user_prompt_tokens = tokenizer(user_prompt_text)["input_ids"]
                            
                            user_prompt = np.full(
                                shape=(len(user_prompt_tokens), processor.channels + 1),
                                fill_value=processor.audio_channel_pad,
                                dtype=np.int64,
                            )
                            user_prompt[:, 0] = np.asarray(user_prompt_tokens, dtype=np.int64)
                            
                            # Reset turn
                            turn_input = processor.make_ensemble(prompt_tokens)
                            session.reset_turn(input_ids=user_prompt, include_system_prompt=False, reset_cache=False)
                            
                            # Encode text tokens
                            text_tokens = tokenizer.encode(text, add_special_tokens=False)
                            print(f"DEBUG: Pushing {len(text_tokens)} tokens", flush=True)
                            
                            if len(text_tokens) > 0:
                                audio_frames = session.push_text_tokens(text_tokens)
                                print(f"DEBUG: Got {len(audio_frames)} frames", flush=True)
                                
                                for frame in audio_frames:
                                    if frame.dim() == 3:
                                        frame = frame[0]
                                    if frame.numel() == 0:
                                        continue
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
                                            asyncio.run_coroutine_threadsafe(
                                                audio_queue.put(pcm_bytes), loop
                                            )
                                            audio_chunks_sent += 1
                            
                            # End text and drain
                            print(f"DEBUG: Calling end_text()", flush=True)
                            final_frames = session.end_text()
                            print(f"DEBUG: Got {len(final_frames)} final frames", flush=True)
                            
                            for frame in final_frames:
                                if frame.dim() == 3:
                                    frame = frame[0]
                                if frame.numel() == 0:
                                    continue
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
                                        asyncio.run_coroutine_threadsafe(
                                            audio_queue.put(pcm_bytes), loop
                                        )
                                        audio_chunks_sent += 1
                            
                            # Drain
                            drain_count = 0
                            while not session.inferencer.is_finished and drain_count < 500:
                                drain_frames = session.drain(max_steps=1)
                                if not drain_frames:
                                    break
                                drain_count += 1
                                for frame in drain_frames:
                                    if frame.dim() == 3:
                                        frame = frame[0]
                                    if frame.numel() == 0:
                                        continue
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
                                            asyncio.run_coroutine_threadsafe(
                                                audio_queue.put(pcm_bytes), loop
                                            )
                                            audio_chunks_sent += 1
                            
                            print(f"DEBUG: Drained {drain_count} frames, sent {audio_chunks_sent} total", flush=True)
                            
                            # Flush remaining
                            final_chunk = decoder.flush()
                            if final_chunk is not None and final_chunk.numel() > 0:
                                pcm_bytes = tensor_to_pcm_bytes(final_chunk)
                                if pcm_bytes:
                                    asyncio.run_coroutine_threadsafe(
                                        audio_queue.put(pcm_bytes), loop
                                    )
                                    audio_chunks_sent += 1
                            
                            print(f"DEBUG: Generation complete, {audio_chunks_sent} chunks", flush=True)
                            break  # Exit loop after processing
                        
                        # Small sleep to prevent busy-waiting
                        __import__('time').sleep(0.01)
                
            except Exception as e:
                print(f"CRITICAL: Audio thread crashed: {e}", flush=True)
                import traceback
                traceback.print_exc()
                state['error'] = str(e)
            finally:
                # Signal completion
                asyncio.run_coroutine_threadsafe(audio_queue.put(b"[DONE]"), loop)
                print(f"DEBUG: Generator thread exiting", flush=True)
        
        # Start the generator thread
        generator_thread = threading.Thread(target=generate_audio_thread, daemon=True)
        generator_thread.start()
        
        # Send ready signal
        await websocket.send_text(json.dumps({"status": "ready"}))
        print(f"DEBUG: Sent ready signal", flush=True)
        
        # Async task to receive text from client
        async def receive_text_task():
            try:
                while True:
                    message = await websocket.receive_text()
                    data = json.loads(message)
                    
                    if data.get("type") == "end":
                        print(f"DEBUG: Received END, text: '{state['text_buffer'][:50]}...'", flush=True)
                        state['finished'] = True
                        break
                    elif data.get("type") == "text":
                        text_chunk = data.get("text", "")
                        if text_chunk:
                            state['text_buffer'] += text_chunk
                            print(f"DEBUG: Received text chunk: '{text_chunk}'", flush=True)
                    else:
                        print(f"DEBUG: Unknown message type: {data.get('type')}", flush=True)
                        
            except WebSocketDisconnect:
                print("DEBUG: WebSocket disconnected", flush=True)
                state['finished'] = True
            except Exception as e:
                print(f"ERROR in receive task: {e}", flush=True)
                state['finished'] = True
        
        # Start receive task
        receive_task = asyncio.create_task(receive_text_task())
        
        # Main loop: send audio chunks as they're produced
        audio_chunks_forwarded = 0
        while True:
            audio_bytes = await audio_queue.get()
            if audio_bytes == b"[DONE]":
                print(f"DEBUG: Received DONE signal from generator", flush=True)
                break
            
            await websocket.send_bytes(audio_bytes)
            audio_chunks_forwarded += 1
        
        # Wait for receive task to complete
        await receive_task
        
        # Send completion status
        await websocket.send_text(json.dumps({
            "status": "complete",
            "chunks": audio_chunks_forwarded
        }))
        
        print(f"DEBUG: WebSocket handler complete, forwarded {audio_chunks_forwarded} chunks", flush=True)
        
    except Exception as e:
        print(f"ERROR WebSocket handler: {e}", flush=True)
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_text(json.dumps({"error": str(e)}))
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass
        print("DEBUG: WebSocket closed", flush=True)
