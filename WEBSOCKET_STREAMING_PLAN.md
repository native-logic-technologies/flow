# WebSocket Streaming Solution for <500ms Latency

## The Problem (Why We're at 2-4s instead of 500ms)

```
Current Flow (BROKEN - 4000ms):
1. LLM generates: "Hi there! How's your day going?" (250ms)
2. Rust buffers ENTIRE sentence (0ms - just waiting)
3. Rust sends full text to TTS via HTTP POST
4. MOSS-TTS processes all 35 characters at once
5. MOSS-TTS generates ALL audio (2000ms)
6. MOSS-TTS streams chunks back
7. Browser plays audio

Total: 250 + 2000 + overhead = 4000ms
```

## The Solution (Token-by-Token Streaming - 280ms)

```
New Flow (FIXED - 280ms):
1. LLM generates: "Hi" (60ms TTFT)
2. Rust sends "Hi" to TTS via WebSocket instantly (1ms)
3. MOSS-TTS buffers: "Hi" (needs 12 tokens total)
4. LLM generates: " there" (60ms)
5. Rust sends " there" to TTS via WebSocket (1ms)
6. MOSS-TTS buffers: "Hi there" (8 tokens)
7. LLM generates: "!" (30ms)
8. MOSS-TTS hits 12-token threshold, starts generating audio!
9. First audio chunk streams back (150ms)
10. Browser plays audio

Total: 60 + 60 + 30 + 150 = 300ms
```

## Implementation Required

### 1. Add WebSocket Endpoint to MOSS-TTS (FastAPI)

File: `tts/moss_tts_fastapi_server.py`

```python
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/v1/audio/stream")
async def websocket_tts(websocket: WebSocket):
    await websocket.accept()
    
    # Initialize MOSS-TTS streaming session
    session = MossTTSRealtimeStreamingSession(...)
    decoder = AudioStreamDecoder(...)
    
    while True:
        message = await websocket.receive_text()
        
        if message == "[END]":
            # Finalize and send remaining audio
            session.end_text()
            break
        
        # Feed text chunk to MOSS-TTS immediately
        text_tokens = tokenizer.encode(message, add_special_tokens=False)
        audio_frames = session.push_text_tokens(text_tokens)
        
        # Process and yield audio chunks immediately
        for frame in audio_frames:
            decoder.push_tokens(frame)
            for wav in decoder.audio_chunks():
                pcm_bytes = tensor_to_pcm_bytes(wav)
                await websocket.send_bytes(pcm_bytes)
```

### 2. Update Rust Orchestrator

File: `orchestrator/src/agent.rs`

```rust
// Inside process_llm_tts, instead of buffering:

// Open WebSocket to TTS
let mut tts_ws = tokio_tungstenite::connect("ws://localhost:8002/v1/audio/stream").await?;

// Stream LLM tokens to TTS as they arrive
while let Some(token) = llm_stream.next().await {
    // Send text token to TTS instantly
    tts_ws.send(Message::Text(token)).await?;
    
    // Poll for incoming audio from TTS
    if let Ok(audio_msg) = tts_ws.try_next().await {
        // Forward audio to browser immediately!
        browser_ws.send(audio_msg).await?;
    }
}

// Signal end of text
tts_ws.send(Message::Text("[END]".to_string())).await?;
```

### 3. Browser Receives Audio Immediately

```javascript
// Browser WebSocket receives audio chunks as soon as TTS generates them
ws.onmessage = async (event) => {
    if (event.data instanceof ArrayBuffer) {
        // Play audio chunk immediately (no waiting for full sentence)
        await playAudio(event.data);
    }
};
```

## Why This Works

**MOSS-TTS-Realtime** is designed for streaming:
- It buffers text tokens internally (12 token delay)
- Once it has enough tokens, it generates audio in chunks
- By feeding tokens as they arrive from LLM, we overlap:
  - LLM generation time
  - TTS processing time
  - Network transmission time

**Result:** Sub-500ms latency without changing the model!

## Current Status

- ✅ MOSS-TTS reverted to working state
- ✅ Clean audio (no AGC distortion)
- ✅ Sentence-level streaming (2.2s latency)
- ❌ Token-by-token streaming (needs implementation)

## Next Steps

1. **Add WebSocket endpoint to MOSS-TTS** (2 hours)
2. **Update Rust orchestrator** (2 hours)
3. **Test end-to-end** (1 hour)

**Estimated final latency: 300-500ms**
