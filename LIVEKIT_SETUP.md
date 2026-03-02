# LiveKit S2S Agent Setup Guide

## Architecture Overview

```
┌─────────────────┐     WebRTC      ┌──────────────────┐
│   Browser       │◄───────────────►│  LiveKit Server  │
│   (User)        │    (Port 7880)  │   (Port 7880)    │
└─────────────────┘                 └────────┬─────────┘
                                             │
                              ┌──────────────┼──────────────┐
                              │              │              │
                              ▼              ▼              ▼
                     ┌─────────────┐ ┌────────────┐ ┌────────────┐
                     │  S2S Agent  │ │  Nemotron  │ │   MOSS     │
                     │   (Rust)    │ │   (LLM)    │ │   (TTS)    │
                     │  (Port ???) │ │ (Port 8000)│ │ (Port 8002)│
                     └──────┬──────┘ └────────────┘ └────────────┘
                            │
                            ▼
                     ┌─────────────┐
                     │  Parakeet   │
                     │   (ASR)     │
                     │(Port 50051) │
                     └─────────────┘
```

## Prerequisites

1. **LiveKit Server** - Install and run on port 7880
2. **LiveKit CLI** - For creating tokens
3. **Rust toolchain** - For building the orchestrator
4. **Services** - Nemotron (8000), MOSS-TTS (8002), Parakeet (50051)

## Installation Steps

### 1. Install LiveKit Server

```bash
# Download LiveKit server
curl -sL https://github.com/livekit/livekit/releases/latest/download/livekit-linux-arm64.tar.gz | tar xvz
sudo mv livekit /usr/local/bin/

# Create config
cat > livekit.yaml << 'CONFIG'
port: 7880
bind_addresses:
  - "0.0.0.0"
rtc:
  udp_port: 7882
  tcp_port: 7881
  use_external_ip: false
keys:
  devkey: secret
logging:
  level: info
CONFIG

# Start server
livekit-server --config livekit.yaml &
```

### 2. Build LiveKit S2S Agent

```bash
cd ~/telephony-stack/livekit-orchestrator
cargo build --release
```

### 3. Run the Agent

```bash
export LIVEKIT_URL=ws://localhost:7880
export LIVEKIT_API_KEY=devkey
export LIVEKIT_API_SECRET=secret

./target/release/livekit-s2s-agent
```

## Key Optimizations Implemented

1. **Persistent TTS WebSocket** - Connection opened once per call, not per sentence
2. **Sentence-Level Streaming** - Streams to TTS as sentences complete
3. **LiveKit WebRTC** - Handles A/V sync, jitter buffering, network adaptation
4. **Rust Async** - Lock-free concurrency, zero-copy where possible

## Expected Latency

With this architecture:
- VAD endpointing: 250ms (optimized)
- LLM TTFT: ~60ms (Nemotron at 60 TPS)
- LLM generation: ~200ms (short sentences)
- TTS with cached voice: ~300-400ms
- Network/WebRTC overhead: ~50ms

**Total: ~850-960ms** (down from 4+ seconds)

To hit <500ms, need:
- Token-level streaming (not sentence-level)
- Or use default TTS voice (no cloning overhead)
