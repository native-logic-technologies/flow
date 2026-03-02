# Architecture Comparison: Current vs CleanS2S

## Current Stack (Raw WebSocket)

```
Browser (WebRTC 48kHz) 
  → Cloudflare Tunnel
    → Rust Orchestrator (WebSocket)
      → VAD (Silero)
        → ASR Bridge (HTTP 8003)
          → Parakeet ASR (gRPC 50051)
      → LLM (vLLM HTTP 8000)
      → TTS (MOSS-TTS HTTP 8002)
    → Browser (24kHz PCM)
```

### Current Issues:
1. **HTTP bridging overhead** - ASR/TTS use HTTP instead of native streaming
2. **No media server** - WebSocket doesn't handle media relay efficiently
3. **VAD in orchestrator** - Adds latency (~32ms chunks)
4. **Text-based protocol** - JSON/HTTP adds serialization overhead

---

## CleanS2S Architecture (Recommended)

```
Browser (WebRTC)
  → LiveKit (media server)
    → Parakeet ASR (native streaming)
    → CleanS2S Orchestrator
      → LLM (vLLM with native streaming)
      → MOSS-TTS (native streaming)
    → LiveKit (mixed audio)
```

### Advantages of CleanS2S:

| Feature | Current | CleanS2S |
|---------|---------|----------|
| **Latency** | 2-5s (HTTP bridging) | <500ms (native streaming) |
| **Media Handling** | WebSocket (text) | LiveKit (binary RTP) |
| **ASR** | HTTP polling | Native streaming gRPC |
| **TTS** | HTTP chunks | Native streaming |
| **VAD** | Software (32ms) | Hardware-accelerated |
| **Resilience** | Single point | Load balanced |
| **Scalability** | Limited | Horizontal scale |

### Why CleanS2S is Better:

1. **LiveKit Media Server**: Handles WebRTC → RTP conversion efficiently
2. **Native gRPC Streaming**: ASR/TTS stream continuously, no HTTP overhead
3. **No Bridging**: Direct pipeline from mic → ASR → LLM → TTS → speaker
4. **Hardware VAD**: LiveKit uses hardware-accelerated voice detection

---

## Quick Win: Optimize Current Stack

Before migrating, try these fixes:

### 1. Native gRPC for ASR
Replace HTTP bridge with direct gRPC streaming to Parakeet:
```rust
// Instead of HTTP POST, use streaming gRPC
let mut asr_stream = parakeet_client.streaming_recognize().await?;
asr_stream.send(audio_chunk).await?;
```

### 2. Pre-buffer TTS
Generate TTS for common phrases upfront:
- "Hey there! I'm Phil..."
- "Mmm hmm, I see..."
- "Let me check that..."

### 3. Sentence-Level Streaming
Stream LLM tokens sentence-by-sentence to TTS:
```
LLM: "The weather | in Ghana | is sunny..."
       ↓           ↓           ↓
    TTS(1)       TTS(2)      TTS(3)
       ↓           ↓           ↓
   Audio(1)    Audio(2)    Audio(3)
```

### 4. WebRTC Direct (Bypass Cloudflare)
Use direct WebRTC instead of WebSocket tunneling for lower latency.

---

## Recommendation

**Short term** (today): 
- Fix current stack with sentence-level streaming
- Add WebRTC direct connection
- Pre-buffer common phrases

**Medium term** (this week):
- Migrate ASR to native gRPC streaming
- Remove HTTP bridges

**Long term** (next sprint):
- Migrate to CleanS2S + LiveKit for production

---

## Current Latency Breakdown (Estimated)

| Component | Current | Target |
|-----------|---------|--------|
| Network (Cloudflare) | 50-150ms | 20-50ms (direct) |
| VAD | 32ms | 10ms (hardware) |
| ASR (HTTP bridge) | 500-1000ms | 100-200ms (gRPC) |
| LLM TTFT | 200-500ms | 50-100ms |
| TTS (HTTP) | 300-800ms | 100-200ms |
| Buffer drift | 1000-3000ms | <200ms |
| **Total** | **2-5s** | **<500ms** |

The biggest wins:
1. Remove HTTP bridging (saves 500-1000ms)
2. Fix buffer drift (saves 1000-3000ms)
3. Direct WebRTC (saves 50-100ms)
