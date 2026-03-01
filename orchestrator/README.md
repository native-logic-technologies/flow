# Flow Telephony Orchestrator

High-performance Rust orchestrator for real-time speech-to-speech AI conversations on NVIDIA DGX Spark (GB10).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Flow Orchestrator (Rust)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ Silero VAD       │  │ Ingress Loop     │  │ Egress Loop      │          │
│  │ (ONNX, CPU)      │  │ (Listening)      │  │ (Speaking)       │          │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘          │
│           │                     │                     │                     │
│           ▼                     ▼                     ▼                     │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                        State Machine                                 │  │
│  │  Listening → Processing → Thinking → Speaking → Listening           │  │
│  │                           ↑                │                        │  │
│  │                           └──── Barge-In ──┘                        │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│  Voxtral ASR  │         │ Nemotron LLM  │         │  MOSS-TTS     │
│  Port 8001    │         │  Port 8000    │         │  Port 8002    │
│  (WebSocket)  │         │   (HTTP/SSE)  │         │  (HTTP/PCM)   │
└───────────────┘         └───────────────┘         └───────────────┘
```

## Features

- **Zero-Latency VAD**: Silero v6.2.1 (ONNX) runs on CPU in microseconds
- **Barge-In Support**: Immediate interruption handling with cancellation tokens
- **Streaming Architecture**: Token-by-token LLM → sentence-by-sentence TTS
- **High Concurrency**: Tokio runtime optimized for 300+ concurrent calls
- **Memory Efficient**: GPU VRAM reserved for LLM/ASR, VAD on CPU

## Prerequisites

1. **Rust** (latest stable): https://rustup.rs/
2. **ONNX Runtime**: `ort` crate handles this automatically
3. **Silero VAD Model**:
   ```bash
   mkdir -p models
   wget https://github.com/snakers4/silero-vad/raw/master/files/silero_vad.onnx -O models/silero_vad.onnx
   ```

4. **Backend Services Running**:
   - Nemotron LLM on port 8000
   - Voxtral ASR on port 8001
   - MOSS-TTS on port 8002

## Building

```bash
cd orchestrator

# Development build
cargo build

# Optimized release build
cargo build --release

# Run with debug logging
RUST_LOG=debug cargo run
```

## Configuration

Create a `.env` file:

```bash
# Backend URLs
ASR_WS_URL=ws://127.0.0.1:8001/v1/realtime
LLM_URL=http://127.0.0.1:8000/v1/chat/completions
TTS_URL=http://127.0.0.1:8002/v1/audio/speech

# VAD Model Path
VAD_MODEL_PATH=./models/silero_vad.onnx

# Optional: Voice cloning reference
TTS_VOICE=default

# LLM System Prompt
LLM_SYSTEM_PROMPT="You are a helpful voice assistant for telephone conversations."
```

## Running

```bash
# Start the orchestrator
./target/release/telephony-orchestrator

# Or with cargo
cargo run --release
```

## Performance Tuning

### DGX Spark Specific Optimizations

1. **CPU Affinity**: Reserve cores for vLLM (Python GIL)
   ```rust
   // In main.rs
   #[tokio::main(worker_threads = 16)]
   ```

2. **Network Tuning**: Enable kernel bypass for WebRTC
   ```bash
   sudo ethtool -G eth0 rx 4096 tx 4096
   sudo sysctl -w net.core.rmem_max=134217728
   sudo sysctl -w net.core.wmem_max=134217728
   ```

3. **Lock-Free Buffers**: Using `crossbeam` for audio queue

## API Integration

### Voxtral ASR (WebSocket)

```json
{"type": "audio", "data": "<base64_pcm>"}
{"type": "commit"}  // After 600ms silence
```

### Nemotron LLM (SSE)

```http
POST /v1/chat/completions
Content-Type: application/json

{
  "model": "nvidia/Nemotron-3-Nano-30B",
  "messages": [...],
  "stream": true
}
```

### MOSS-TTS (Streaming)

```http
POST /v1/audio/speech
Content-Type: application/json

{
  "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
  "input": "Hello world",
  "response_format": "pcm"
}
```

## Development

### Project Structure

```
orchestrator/
├── Cargo.toml              # Dependencies
├── src/
│   ├── main.rs            # Entry point
│   ├── vad.rs             # Silero VAD wrapper
│   └── agent.rs           # Telephony agent state machine
├── models/                # ONNX models (gitignored)
└── README.md
```

### Testing

```bash
# Unit tests
cargo test

# Integration tests (requires backend services)
cargo test --features integration -- --ignored
```

## License

[Your License Here]

## Contributing

[Your Contributing Guidelines]
