# Flow Telephony Orchestrator

High-performance Rust orchestrator for real-time speech-to-speech AI conversations on NVIDIA DGX Spark (GB10).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Complete Audio Pipeline (E2E ~250ms)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. LiveKit (Rust)    2. DeepFilterNet     3. Silero VAD                    │
│     Receive 8kHz         Noise Suppression   Voice Detection                 │
│     RTP packets          (< 2ms)             (< 1ms)                         │
│           │                    │                   │                         │
│           └────────────────────┴───────────────────┘                         │
│                              │                                               │
│                              ▼                                               │
│  4. Voxtral ASR (vLLM)   5. Nemotron LLM   6. MOSS-TTS                      │
│     WebSocket              NVFP4 Blackwell   Voice Cloning                   │
│     Port 8001              Port 8000         Port 8002                       │
│     (~40ms)                (~80ms TTFT)      (~100ms)                       │
│                              │                                               │
│                              ▼                                               │
│                    7. LiveKit (Rust)                                         │
│                       Audio Playback                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Features

- **Noise Suppression**: DeepFilterNet v0.5.6 with tract backend (pure Rust)
- **Voice Activity**: Silero VAD v6.2.1 (ONNX, CPU-only)
- **Barge-In Support**: Immediate interruption handling
- **Streaming Architecture**: Token-by-token LLM → sentence-by-sentence TTS
- **Zero-Shot Voice Cloning**: 16kHz mono reference audio
- **High Concurrency**: Tokio runtime for 300+ concurrent calls

## Dependencies

1. **Rust** (latest stable): https://rustup.rs/
2. **Silero VAD Model**: Download from [releases](https://github.com/snakers4/silero-vad/releases)
3. **Backend Services**:
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

# Voice Cloning (WAV, Mono, 16kHz, PCM 16-bit, 3-5 seconds)
TTS_VOICE_FILE=/path/to/reference_voice.wav

# Logging
RUST_LOG=info
```

## Voice Cloning Audio Format

**Critical**: MOSS-TTS requires exact format:

| Parameter | Required | Notes |
|-----------|----------|-------|
| Format | WAV | MP3/M4A causes static |
| Channels | Mono (1) | Stereo causes tensor crash |
| Sample Rate | 16000 Hz | 48kHz wastes compute |
| Duration | 3-5 seconds | <3s: no emotion, >5s: slow |
| Acoustics | Zero noise | Model clones everything |

**Convert with FFmpeg:**
```bash
ffmpeg -i input.mp3 -ac 1 -ar 16000 -c:a pcm_s16le output.wav
```

## DeepFilterNet Integration

The orchestrator includes DeepFilterNet v0.5.6 with the `tract` feature:

```toml
[dependencies]
deep_filter = { version = "0.5.6", features = ["tract"] }
```

This provides:
- Pure Rust implementation (no C++ bindings)
- CPU-only inference (preserves GPU VRAM)
- SIMD optimizations for ARM64/Blackwell
- < 2ms latency per frame

## Running

```bash
# From project root
./scripts/start-orchestrator.sh
```

## Performance Targets

| Component | Latency | Notes |
|-----------|---------|-------|
| DeepFilterNet | < 2ms | Noise suppression |
| Silero VAD | < 1ms | Speech detection |
| Voxtral ASR | ~40ms | Transcription |
| Nemotron LLM | ~80ms | Time to first token |
| MOSS-TTS | ~100ms | Voice synthesis |
| **Total E2E** | **~250ms** | User speaks → hears response |

## Project Structure

```
orchestrator/
├── Cargo.toml              # Dependencies (DeepFilterNet v0.5.6, etc.)
├── .env.example            # Configuration template
├── src/
│   ├── main.rs            # Entry point, Tokio runtime
│   ├── agent.rs           # Telephony state machine
│   ├── audio_pipeline.rs  # DeepFilterNet + VAD integration
│   └── vad.rs             # Silero VAD wrapper
└── models/                # ONNX models (gitignored)
    └── silero_vad.onnx    # Download from GitHub releases
```

## Audio Frame Sizes

Different models require different frame sizes:

| Model | Frame Size | At 8kHz | At 16kHz |
|-------|-----------|---------|----------|
| DeepFilterNet | 160-480 samples | 20-60ms | 10-30ms |
| Silero VAD | 256 samples | 32ms | 16ms |
| WebRTC | Varies | 10-60ms | - |

The orchestrator uses ring buffers to align frames correctly.

## Testing

```bash
# Test individual components
cargo test

# Test full pipeline
../scripts/test-full-pipeline.sh

# Manual voice cloning test
curl -X POST http://localhost:8002/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
    "input": "Hello with cloned voice",
    "response_format": "pcm",
    "extra_body": {"reference_audio": "<base64>"}
  }'
```

## Troubleshooting

### DeepFilterNet won't compile
```bash
# Ensure you have latest Rust
cargo update
```

### VAD model not found
```bash
# Download Silero VAD
curl -L -o models/silero_vad.onnx \
  https://github.com/snakers4/silero-vad/releases/download/v6.2.1/silero_vad.onnx
```

### Audio sounds distorted
- Check reference audio format (must be WAV, mono, 16kHz)
- Verify `TTS_VOICE_FILE` path is absolute
- Ensure no background noise in reference clip

## License

[Your License Here]

## Contributing

[Your Contributing Guidelines]

---

**Built for DGX Spark (GB10) with Blackwell SM121**  
**Target: 300+ concurrent calls with <250ms E2E latency**
