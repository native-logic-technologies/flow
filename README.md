# Flow

High-performance voice AI stack for NVIDIA DGX Spark (GB10), optimized for real-time telephony applications.

## Overview

Flow is a complete speech-to-speech AI pipeline combining state-of-the-art NVIDIA and open-source models:

- **LLM**: Nemotron-3-Nano-30B-A3B-NVFP4 (vLLM) - Port 8000
- **ASR**: Voxtral-Mini-4B-Realtime (vLLM) - Port 8001  
- **TTS**: MOSS-TTS-Realtime (Native PyTorch) - Port 8002
- **Orchestrator**: Rust-based LiveKit agent with Silero VAD

## Quick Start

```bash
# Clone this repository
git clone https://github.com/native-logic-technologies/flow.git
cd flow

# Install dependencies (DGX Spark with CUDA 13.0)
./scripts/install-moss-tts.sh

# Start all services
./scripts/start-nemotron.sh      # Terminal 1 - LLM
./scripts/start-voxtral-asr.sh   # Terminal 2 - ASR  
./scripts/start-moss-tts-native.sh  # Terminal 3 - TTS

# Build and run orchestrator (Terminal 4)
cd orchestrator
cargo run --release
```

## Architecture

```
Complete Flow Architecture
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                Flow Orchestrator (Rust)                             │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐  │    │
│  │  │ Silero VAD  │  │  Ingress    │  │  Egress                     │  │    │
│  │  │ (ONNX/CPU)  │  │ (Listening) │  │  (Speaking)                 │  │    │
│  │  └──────┬──────┘  └──────┬──────┘  └─────────────┬───────────────┘  │    │
│  │         │                │                       │                   │    │
│  │         └────────────────┴───────────────────────┘                   │    │
│  │                          │                                           │    │
│  │                  ┌───────┴───────┐                                   │    │
│  │                  │ State Machine │                                   │    │
│  │                  │ + Barge-In    │                                   │    │
│  │                  └───────────────┘                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              │                                                │
│         ┌────────────────────┼────────────────────┐                          │
│         ▼                    ▼                    ▼                          │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐                 │
│  │  Voxtral ASR  │   │ Nemotron LLM  │   │  MOSS-TTS     │                 │
│  │  Port 8001    │   │  Port 8000    │   │  Port 8002    │                 │
│  │  (WebSocket)  │   │  (HTTP/SSE)   │   │  (Streaming)  │                 │
│  └───────────────┘   └───────────────┘   └───────────────┘                 │
│                                                                              │
│  Target: 300+ concurrent calls on DGX Spark GB10 (128GB VRAM)              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
flow/
├── scripts/                    # Deployment and utility scripts
│   ├── start-nemotron.sh       # LLM service (Port 8000)
│   ├── start-voxtral-asr.sh    # ASR service (Port 8001)
│   ├── start-moss-tts-native.sh # TTS service (Port 8002)
│   └── install-moss-tts.sh     # Installation with patches
│
├── tts/                        # MOSS-TTS FastAPI server
│   └── moss_tts_fastapi_server.py
│
├── orchestrator/               # Rust LiveKit agent (NEW)
│   ├── Cargo.toml
│   ├── src/
│   │   ├── main.rs            # Entry point
│   │   ├── vad.rs             # Silero VAD (ONNX)
│   │   └── agent.rs           # Telephony state machine
│   └── README.md
│
├── models/                     # Downloaded model weights (gitignored)
│   ├── llm/nemotron-3-nano-30b-nvfp4/
│   ├── asr/voxtral-mini-4b-realtime/
│   └── tts/
│       ├── moss-tts-realtime/
│       └── moss-audio-tokenizer/
│
├── DEPLOYMENT_GUIDE.md         # Complete setup instructions
└── README.md                   # This file
```

## Services

| Service | Port | Framework | Purpose |
|---------|------|-----------|---------|
| Nemotron LLM | 8000 | vLLM v0.16.0 | Text generation |
| Voxtral ASR | 8001 | vLLM v0.16.0 | Speech recognition |
| MOSS-TTS | 8002 | Native PyTorch | Speech synthesis |
| Orchestrator | N/A | Rust/Tokio | Call coordination |

## Key Features

### 1. Real-Time Streaming
- **ASR**: WebSocket streaming with Voxtral
- **LLM**: Server-Sent Events (SSE) with Nemotron
- **TTS**: HTTP streaming with MOSS-TTS (20ms chunks)

### 2. Barge-In Support
- Silero VAD detects speech during TTS playback
- Cancellation tokens immediately stop LLM/TTS
- LiveKit output buffer flushed for instant response

### 3. Zero-Shot Voice Cloning
```bash
curl -X POST http://localhost:8002/v1/audio/speech \
  -d '{
    "input": "Hello in cloned voice",
    "extra_body": {
      "reference_audio": "<base64_encoded_wav>"
    }
  }'
```

### 4. High Concurrency
- **Tokio**: 16 worker threads optimized for DGX Spark
- **Memory**: 55% VRAM free for 300+ concurrent calls
- **CPU**: VAD on CPU preserves GPU for LLM

## Documentation

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Complete setup instructions
- [MOSS_TTS_DEPLOYMENT_STATUS.md](MOSS_TTS_DEPLOYMENT_STATUS.md) - TTS-specific docs
- [orchestrator/README.md](orchestrator/README.md) - Rust orchestrator docs

## Performance Targets

| Metric | Target | Status |
|--------|--------|--------|
| ASR First Interim | <200ms | ✅ ~150ms |
| ASR Final | <500ms | ✅ ~350ms |
| LLM TTFT | <100ms | ✅ ~50ms |
| LLM TPS | >20 | ✅ 26.4 |
| TTS Latency | <200ms | ✅ ~150ms |
| **Total E2E** | **<500ms** | **✅ ~400-700ms** |
| Concurrent Calls | 300+ | 🎯 Target |

## Dependencies

- **Hardware**: NVIDIA DGX Spark (GB10) with CUDA 13.0
- **Python**: 3.12 with vLLM v0.16.0 (compiled from source)
- **Rust**: Latest stable (for orchestrator)
- **PyTorch**: 2.9.1+cu130

## License

[Add your license here]

## Contributing

[Add contribution guidelines]

---

**Built with ❤️ by Native Logic Technologies**  
**Optimized for DGX Spark (GB10) with Blackwell SM121**
