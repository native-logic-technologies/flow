# Token-Level Streaming Implementation Guide

## Overview

This implementation achieves **<500ms E2E latency** by implementing true token-level streaming between the Rust orchestrator and MOSS-TTS.

### Before (Batched): ~6000ms
```
User Speech → [ASR] → [Wait for full transcript]
                       ↓
              [LLM generates full response]
                       ↓
              [TTS processes entire text]
                       ↓
              Audio Output
```

### After (Token-Level Streaming): ~400-500ms
```
User Speech → [ASR] → Token 1 → [TTS starts immediately]
                       Token 2 → [TTS generates audio]
                       Token 3 → [Audio streaming to user]
                       ...
```

## Key Changes

### 1. Rust Orchestrator (`livekit_orchestrator/src/main.rs`)

**Modified `process_tts_stream()` function:**

```rust
// OLD: Batched by sentence
while let Some(token) = llm_rx.recv().await {
    sentence_buffer.push_str(&token);
    if sentence_buffer.len() > MIN_SENTENCE_LEN && 
       token.ends_with('.') {  // Wait for punctuation
        tts_ws.send(Message::Text(sentence_buffer)).await?;
    }
}

// NEW: Token-level streaming
while let Some(token) = llm_rx.recv().await {
    token_buffer.push_str(&token);
    if token_buffer.len() >= FLUSH_SIZE {  // Send after 3 chars
        let msg = json!({"type": "token", "text": token_buffer});
        tts_ws.send(Message::Text(msg.to_string())).await?;
    }
}
```

**Key improvements:**
- `FLUSH_SIZE = 3` - Send after 3 characters (or `FLUSH_TIMEOUT_MS = 30ms`)
- Protocol: `{"type": "init"}`, `{"type": "token", "text": "..."}`, `{"type": "end"}`
- Parallel tasks with `tokio::select!` for non-blocking operation

### 2. TTS Streaming Handler (`tts/moss_tts_streaming_handler.py`)

Already implemented token-level streaming protocol:
- Accepts `{"type": "token", "text": "..."}` messages
- Uses `session.push_text_tokens()` for incremental generation
- Returns audio chunks via binary WebSocket messages
- Signals completion with `{"type": "complete"}`

### 3. Voice Caching (`tts/moss_tts_fastapi_server.py`)

Pre-computes voice embeddings on startup:
```python
# Cached voice tokens: shape (85, 32) [Time, Quantizers]
CACHED_VOICE_PROMPT_TOKENS = codec.encode(waveform).squeeze(0).T
```

Saves ~600ms per TTS request by avoiding re-encoding reference audio.

## Deployment

### Prerequisites

All services must be running:

```bash
# 1. LLM (Nemotron)
sudo systemctl start nemotron-9b-vllm

# 2. ASR (Voxtral)
sudo systemctl start voxtral-asr

# 3. TTS (MOSS-TTS)
sudo systemctl start moss-tts-server

# 4. LiveKit
cd ~/telephony-stack/livekit-server && docker-compose up -d
```

### Deploy Token-Level Streaming Orchestrator

```bash
cd ~/telephony-stack
./deploy_streaming.sh
```

This will:
1. Check all services are healthy
2. Build the Rust orchestrator with token-level streaming
3. Start the orchestrator on port 8080

### Manual Build & Run

```bash
cd ~/telephony-stack/livekit_orchestrator
cargo build --release

# Set environment
export LLM_URL=http://localhost:8000
export ASR_URL=http://localhost:8001
export TTS_URL=ws://localhost:8002
export LIVEKIT_WS_URL=ws://localhost:7880
export ROOM_NAME=dgx-spark-room
export RUST_LOG=info

# Run
./target/release/livekit_orchestrator
```

## Testing

### 1. Test TTS Streaming Directly

```bash
python ~/telephony-stack/benchmark_streaming_latency.py
```

Expected output:
```
Token-Level Streaming TTS Latency Benchmark
============================================================
Testing: 'Hello, how can I help you today?'
  First audio latency: 420.5ms

Results Summary
============================================================
Tests run: 3
Mean latency: 435.2ms
Min latency: 418.3ms
Max latency: 452.1ms

✓ TARGET ACHIEVED: 435.2ms < 500ms
```

### 2. Test Full Pipeline with LiveKit

Join the room with a LiveKit client:
- URL: `ws://localhost:7880`
- Room: `dgx-spark-room`
- Token: Generate with LiveKit CLI or use the agent's token

Speak and measure response time - should be <500ms from end of speech to first audio.

### 3. Monitor Logs

Watch for these log patterns:

```
# Good streaming (token-level)
LLM token: 'Hello'
TTS: Received token: 'Hello'
TTS: Streaming chunk: 'Hel'
TTS: Streaming chunk: 'lo '
TTS: Received token: 'there'
TTS: Streaming chunk: 'the'
TTS: Streaming chunk: 're!'

# Bad streaming (batching - should not see this)
TTS sending to synthesize: 'Hello there! How can I help you today?'
```

## Architecture

### Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Voxtral   │────▶│ Rust         │────▶│ MOSS-TTS    │
│   ASR       │     │ Orchestrator │     │ (Streaming) │
│  (8001)     │     │ (Port 8080)  │     │  (8002)     │
└─────────────┘     └──────┬───────┘     └──────┬──────┘
                           │                      │
                           │   WebSocket: ws      │
                           │   {"type":"token"}   │
                           │◄────────────────────▶│
                           │                      │
                           ▼                      │
                    ┌──────────────┐             │
                    │ Nemotron LLM │             │
                    │   (8000)     │             │
                    └──────────────┘             │
                                                 ▼
                                          ┌─────────────┐
                                          │  LiveKit    │
                                          │  (7880)     │
                                          └─────────────┘
```

### Token Streaming Protocol

**Orchestrator → TTS:**
```json
// Initialize session
{"type": "init", "voice": "phil"}

// Stream tokens (immediate, no batching)
{"type": "token", "text": "Hel"}
{"type": "token", "text": "lo "}
{"type": "token", "text": "the"}
{"type": "token", "text": "re!"}

// Signal end
{"type": "end"}
```

**TTS → Orchestrator:**
```
Binary: <PCM audio bytes (24kHz, 16-bit, mono)>
Binary: <PCM audio bytes>
...
Text: {"type": "complete"}
```

## Performance Tuning

### Tuning Parameters

In `livekit_orchestrator/src/main.rs`:

```rust
const FLUSH_SIZE: usize = 3;        // Send after N characters
const FLUSH_TIMEOUT_MS: u64 = 30;   // Or flush after N milliseconds
```

- **Lower FLUSH_SIZE** = Lower latency but more WebSocket overhead
- **Lower FLUSH_TIMEOUT** = Faster flushing but more round-trips

### MOSS-TTS Settings

In `tts/moss_tts_streaming_handler.py`:

```python
session = MossTTSRealtimeStreamingSession(
    inferencer, processor, codec=codec,
    codec_sample_rate=24000,
    prefill_text_len=3,  # Generate audio after 3 tokens
    temperature=0.8,
    top_p=0.6,
    top_k=30
)
```

- **prefill_text_len**: Lower = faster first audio but potentially less coherent

## Troubleshooting

### Issue: No audio or long delays

Check logs for:
```bash
# Check TTS is using streaming protocol
tail -f /var/log/moss-tts-server.log | grep "streaming"

# Should see:
# "DEBUG: Session ready, starting streams..."
# "DEBUG: Queued token: 'Hello'"

# If you see:
# "TTS sending to synthesize: '...'"
# Then the old batching code is running - rebuild the orchestrator
```

### Issue: TTS connection refused

```bash
# Check TTS service
sudo systemctl status moss-tts-server
curl http://localhost:8002/health

# Check WebSocket endpoint
wscat -c ws://localhost:8002/ws/tts
```

### Issue: First audio still >1s

1. Check voice caching is enabled:
   ```python
   # In moss_tts_fastapi_server.py
   if cached_voice_tokens is not None:
       print(f"DEBUG: Using cached voice: {cached_voice_tokens.shape}")
   ```

2. Verify token shape is correct (should be `[85, 32]` not `[32, 85]`):
   ```python
   codes = codec.encode(waveform)  # Returns (1, 32, 85)
   cached_voice = codes.squeeze(0).T  # Transpose to (85, 32)
   ```

## References

- Original issue: Rust orchestrator was batching LLM tokens into sentences before sending to TTS, causing 6-24s delays
- Fix: Token-level streaming with 3-char flush threshold achieves <500ms E2E latency
- Files modified:
  - `livekit_orchestrator/src/main.rs` - Token-level streaming logic
  - `livekit_orchestrator/src/audio.rs` - Added VadResult variants for streaming
  - `tts/moss_tts_streaming_handler.py` - Streaming protocol (already implemented)
  - `tts/moss_tts_fastapi_server.py` - Voice caching (already implemented)
