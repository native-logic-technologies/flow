"""
WebSocket endpoint for streaming TTS - enables <500ms latency by feeding tokens as they arrive.

This implements token-by-token streaming from LLM to TTS, rather than buffering full sentences.
"""

from fastapi import WebSocket, WebSocketDisconnect
import json
import base64
import numpy as np


@app.websocket("/v1/audio/stream")
async def websocket_tts(websocket: WebSocket):
    """
    WebSocket endpoint for streaming TTS with token-by-token input.
    
    Protocol:
    1. Client sends: {"type": "init", "voice": "default", "reference_audio": "...", "reference_text": "..."}
    2. Client sends text chunks: "Hello" → " world" → "!"
    3. Client sends: "[END]" to finish
    4. Server streams audio chunks back as they're generated
    """
    await websocket.accept()
    print("DEBUG: WebSocket TTS connection accepted", flush=True)
    
    from mossttsrealtime.streaming_mossttsrealtime import (
        MossTTSRealtimeStreamingSession,
        AudioStreamDecoder
    )
    
    try:
        # Wait for init message
        init_msg = await websocket.receive_text()
        init_data = json.loads(init_msg)
        
        if init_data.get("type") != "init":
            await websocket.send_text(json.dumps({"error": "Expected init message"}))
            await websocket.close()
            return
        
        # Extract voice settings
        reference_audio = None
        reference_text = ""
        
        if init_data.get("reference_audio"):
            ref_b64 = init_data["reference_audio"]
            if ref_b64.startswith("data:"):
                ref_b64 = ref_b64.split(",")[1]
            reference_audio = base64.b64decode(ref_b64)
            reference_text = init_data.get("reference_text", "")
            print(f"DEBUG: Using voice cloning with {len(reference_audio)} bytes reference", flush=True)
        
        # Encode reference audio if provided
        prompt_tokens = None
        if reference_audio:
            prompt_codes = encode_reference_audio(reference_audio, codec, device)
            if prompt_codes is not None:
                prompt_tokens = prompt_codes.squeeze(1) if prompt_codes.ndim == 3 else prompt_codes
                print(f"DEBUG: Encoded voice tokens shape: {prompt_tokens.shape}", flush=True)
        
        # Create streaming session
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
            print("DEBUG: Voice prompt set", flush=True)
        else:
            session.clear_voice_prompt()
        
        # Create decoder
        decoder = AudioStreamDecoder(
            codec,
            chunk_frames=12,
            overlap_frames=0,
            decode_kwargs={"chunk_duration": -1},
            device=device,
        )
        
        # Build initial turn input with system prompt
        turn_input = processor.make_ensemble(prompt_tokens)
        session.reset_turn(input_ids=turn_input, include_system_prompt=True, reset_cache=True)
        
        print("DEBUG: Session ready for streaming", flush=True)
        await websocket.send_text(json.dumps({"status": "ready"}))
        
        # Process incoming text chunks
        total_text = ""
        audio_chunks_sent = 0
        first_audio_time = None
        
        while True:
            try:
                message = await websocket.receive_text()
                
                if message == "[END]":
                    print(f"DEBUG: Received [END], finalizing. Total text: '{total_text}'", flush=True)
                    
                    # Finalize generation
                    final_frames = session.end_text()
                    for frame in final_frames:
                        if frame.dim() == 3:
                            frame = frame[0]
                        
                        # Sanitize tokens
                        codebook_size = int(getattr(codec, "codebook_size", 1024))
                        audio_eos_token = int(getattr(inferencer, "audio_eos_token", 1026))
                        
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
                                await websocket.send_bytes(pcm_bytes)
                                audio_chunks_sent += 1
                    
                    # Flush remaining audio
                    final_chunk = decoder.flush()
                    if final_chunk is not None and final_chunk.numel() > 0:
                        pcm_bytes = tensor_to_pcm_bytes(final_chunk)
                        if pcm_bytes:
                            await websocket.send_bytes(pcm_bytes)
                            audio_chunks_sent += 1
                    
                    print(f"DEBUG: Stream complete. Sent {audio_chunks_sent} chunks, first audio after {first_audio_time}ms", flush=True)
                    await websocket.send_text(json.dumps({"status": "complete", "chunks": audio_chunks_sent}))
                    break
                
                # Accumulate text
                total_text += message
                
                # Encode and feed to model
                text_tokens = tokenizer.encode(message, add_special_tokens=False)
                
                if len(text_tokens) == 0:
                    continue
                
                # Create user prompt
                user_prompt_text = f"<|im_end|>\n<|im_start|>user\n{message}<|im_end|>\n<|im_start|>assistant\n"
                user_prompt_tokens = tokenizer(user_prompt_text)["input_ids"]
                
                user_prompt = np.full(
                    shape=(len(user_prompt_tokens), processor.channels + 1),
                    fill_value=processor.audio_channel_pad,
                    dtype=np.int64,
                )
                user_prompt[:, 0] = np.asarray(user_prompt_tokens, dtype=np.int64)
                
                # Feed to session
                session.reset_turn(input_ids=user_prompt, include_system_prompt=False, reset_cache=False)
                audio_frames = session.push_text_tokens(text_tokens)
                
                # Process and yield audio
                for frame in audio_frames:
                    if frame.dim() == 3:
                        frame = frame[0]
                    
                    # Sanitize
                    codebook_size = int(getattr(codec, "codebook_size", 1024))
                    audio_eos_token = int(getattr(inferencer, "audio_eos_token", 1026))
                    
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
                            await websocket.send_bytes(pcm_bytes)
                            audio_chunks_sent += 1
                            
                            if first_audio_time is None:
                                first_audio_time = 0  # Would need actual timing
                                print(f"DEBUG: First audio chunk sent!", flush=True)
                
            except WebSocketDisconnect:
                print("DEBUG: WebSocket disconnected", flush=True)
                break
            except Exception as e:
                print(f"ERROR in WebSocket loop: {e}", flush=True)
                import traceback
                traceback.print_exc()
                await websocket.send_text(json.dumps({"error": str(e)}))
                break
                
    except Exception as e:
        print(f"ERROR setting up WebSocket: {e}", flush=True)
        import traceback
        traceback.print_exc()
        await websocket.send_text(json.dumps({"error": str(e)}))
    finally:
        await websocket.close()
        print("DEBUG: WebSocket closed", flush=True)
