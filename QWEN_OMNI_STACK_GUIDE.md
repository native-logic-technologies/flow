# Qwen Omni Stack - Complete Deployment Guide

## Overview

The **Qwen Omni Stack** is a production-ready Speech-to-Speech (S2S) AI system built on NVIDIA DGX Spark (Blackwell/ARM64). It uses state-of-the-art Qwen models with native multimodal support and emotional intelligence.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Qwen Omni Stack                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  🎤 Ear (Port 8001)                                            │
│  Qwen2.5-Omni-7B (21GB, FP8)                                   │
│  • Native audio understanding                                   │
│  • Emotion detection from speech                                │
│  • Multimodal: Audio + Vision + Text                            │
│                                                                 │
│                    ↓ [Emotion + Transcript]                    │
│                                                                 │
│  🧠 Brain (Port 8000)                                          │
│  Qwen3.5-9B-NVFP4 (17GB, NVFP4)                                │
│  • Emotional reasoning and response                             │
│  • Vision support for WhatsApp KYC                              │
│  • Tool use and function calling                                │
│                                                                 │
│                    ↓ [Emotion + Response]                      │
│                                                                 │
│  🎙️ Voice (Port 8002)                                           │
│  MOSS-TTS-Realtime (4.4GB)                                     │
│  • Zero-shot voice cloning                                      │
│  • Emotional voice matching                                     │
│  • 5 emotion voice caches                                       │
│                                                                 │
│                    ↓ [PCM Audio]                               │
│                                                                 │
│  📞 User hears emotionally matched response                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Models

| Component | Model | Size | Quantization | Purpose |
|-----------|-------|------|--------------|---------|
| Ear | Qwen2.5-Omni-7B | 21GB | FP8 | Audio understanding + emotion |
| Brain | Qwen3.5-9B-NVFP4 | 17GB | NVFP4 | Reasoning + vision |
| Voice | MOSS-TTS-Realtime | 4.4GB | BF16 | Emotional voice synthesis |
| **Total** | | **~42GB** | | |

## Hardware Requirements

- **Platform**: ARM64 (aarch64) - DGX Spark, GB10, Blackwell
- **VRAM**: 80GB+ recommended (128GB unified memory on DGX Spark)
- **Storage**: ~50GB for models + ~20GB for Docker images
- **Network**: Internet access for model downloads

## Quick Start

### 1. Start the Full Stack

```bash
cd /home/phil/telephony-stack
./start_qwen_omni_stack.sh
```

This starts all components in order:
1. 🧠 Brain (Qwen3.5-9B-NVFP4) on port 8000
2. 🎤 Ear (Qwen2.5-Omni-7B) on port 8001
3. 🎙️ Voice (MOSS-TTS-Realtime) on port 8002
4. 📞 Orchestrator on port 8080

### 2. Test the Stack

```bash
./test_qwen_omni.sh
```

### 3. Start Individual Components

```bash
# Brain only
./start_qwen_brain.sh

# Ear only
./start_qwen_ear.sh

# Voice only
./start_qwen_voice.sh
```

## Component Details

### 🧠 Brain (Qwen3.5-9B-NVFP4)

**File**: `start_qwen_brain.sh`
**Port**: 8000
**Docker**: `vllm/vllm-openai@sha256:b6fcb1a...`

**Features**:
- NVFP4 quantization (4-bit weights, 8-bit activations)
- FP8 KV-cache
- Max 16384 token context
- Vision support for image analysis

**Usage**:
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/models/quantized/Qwen3.5-9B-NVFP4",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**Vision Example** (WhatsApp KYC):
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/models/quantized/Qwen3.5-9B-NVFP4",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "Verify this ID document"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
      ]
    }]
  }'
```

### 🎤 Ear (Qwen2.5-Omni-7B)

**File**: `start_qwen_ear.sh`
**Port**: 8001
**Docker**: `vllm/vllm-openai@sha256:b6fcb1a...`

**Features**:
- Native audio understanding (not ASR→Text)
- Emotion detection from speech patterns
- Multimodal: processes audio directly

**Usage**:
```bash
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/models/Qwen2.5-Omni-7B",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "Transcribe with emotion:"},
        {"type": "input_audio", "input_audio": {"data": "base64_audio", "format": "wav"}}
      ]
    }]
  }'
```

### 🎙️ Voice (MOSS-TTS-Realtime)

**File**: `start_qwen_voice.sh`
**Port**: 8002
**Type**: Native Python (not Docker)

**Features**:
- Zero-shot voice cloning
- 5 emotional voice caches
- 24kHz output
- OpenAI-compatible `/v1/audio/speech` endpoint

**Voice Emotions**:
- `neutral` - Balanced, professional
- `empathetic` - Soft, caring, lower pitch
- `cheerful` - Higher energy, smiling
- `thinking` - Measured, contemplative
- `urgent` - Faster, more focused

**Usage**:
```bash
curl http://localhost:8002/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Hello, how can I help?",
    "voice": "empathetic"
  }' \
  --output response.pcm

# Play audio
ffplay -f s16le -ar 24000 -ac 1 response.pcm
```

### 📞 Orchestrator

**File**: `qwen_omni_orchestrator.py`
**Port**: 8080
**Type**: Native Python with FastAPI

**Features**:
- Connects Ear → Brain → Voice
- Emotional metadata bridge
- Twilio WebSocket integration
- Conversation state management

**Twilio Integration**:
```bash
# Set webhook URL
export STREAM_URL=wss://your-server:8080/twilio/stream
./start_qwen_omni_stack.sh
```

## Voice Sample Setup

For emotional voice cloning, record 3.5-second samples:

```bash
voices/
├── neutral/reference.wav      # "Hi, I'm Phil..."
├── empathetic/reference.wav   # "Oh, I understand..."
├── cheerful/reference.wav     # "That's wonderful!"
├── thinking/reference.wav     # "Hmm, let me think..."
└── urgent/reference.wav       # "This is important..."
```

**Format**: 24kHz, mono, 16-bit WAV

## Emotional Flow

```
User speaks → [Ear detects emotion] → [Brain matches emotion] → [Voice uses emotional tone]

Example:
  User: [FRUSTRATED] "This is broken!"
    ↓
  Ear: Detects frustration from audio
    ↓
  Brain: <EMPATHETIC> "I'm so sorry... let me fix this."
    ↓
  Voice: Uses empathetic voice cache (soft, caring)
    ↓
  User hears: Genuine concern, not robotic cheerfulness
```

## Monitoring

### Logs
```bash
# Brain
docker logs -f qwen-brain

# Ear
docker logs -f qwen-ear

# Voice
tail -f /tmp/tts.log

# Orchestrator
tail -f /tmp/orchestrator.log
```

### Health Checks
```bash
curl http://localhost:8000/health  # Brain
curl http://localhost:8001/health  # Ear
curl http://localhost:8002/health  # Voice
curl http://localhost:8080/health  # Orchestrator
```

### VRAM Usage
```bash
watch -n 1 nvidia-smi
```

## Troubleshooting

### Container Won't Start
```bash
# Check if port is in use
lsof -i :8000

# Kill existing containers
docker stop qwen-brain qwen-ear
docker rm qwen-brain qwen-ear

# Restart
./start_qwen_omni_stack.sh
```

### Model Not Found
```bash
# Verify models exist
ls /home/phil/telephony-stack/models/Qwen2.5-Omni-7B
ls /home/phil/telephony-stack/models/quantized/Qwen3.5-9B-NVFP4

# If missing, download:
# (Script will auto-download on first run)
```

### Out of VRAM
```bash
# Reduce GPU memory utilization in scripts
# Edit start_qwen_brain.sh:
#   --gpu-memory-utilization 0.5  # Instead of 0.7
```

### Audio Quality Issues
```bash
# Check voice samples exist
ls voices/*/reference.wav

# Record new samples if needed
# Format: 24kHz, mono, WAV, 3-4 seconds
```

## API Reference

### Brain (Port 8000)
- `GET /health` - Health check
- `POST /v1/chat/completions` - OpenAI-compatible chat

### Ear (Port 8001)
- `GET /health` - Health check
- `POST /v1/chat/completions` - Multimodal (audio + text)

### Voice (Port 8002)
- `GET /health` - Health check
- `GET /voices` - List available voices
- `POST /v1/audio/speech` - Text-to-speech

### Orchestrator (Port 8080)
- `GET /health` - Health check
- `POST /twilio/inbound` - Twilio webhook
- `WS /twilio/stream` - WebSocket stream

## Performance

| Metric | Target | Actual |
|--------|--------|--------|
| Brain TTFT | <500ms | ~200ms |
| Ear Processing | <1s | ~800ms |
| TTS Generation | Real-time | ~1x RT |
| E2E Latency | <2s | ~1.5-2s |

*TTFT = Time to First Token, RT = Real-time factor*

## Files

| File | Purpose |
|------|---------|
| `start_qwen_omni_stack.sh` | Start full stack |
| `start_qwen_brain.sh` | Start Brain only |
| `start_qwen_ear.sh` | Start Ear only |
| `start_qwen_voice.sh` | Start Voice only |
| `qwen_omni_orchestrator.py` | Main orchestrator |
| `tts_moss_realtime_server.py` | TTS server |
| `test_qwen_omni.sh` | Test all components |

## Docker Image

**Required**: `vllm/vllm-openai@sha256:b6fcb1a19dad25e60e3e91e98ed36163978778fff2d82416c773ca033aa857eb`

**Architecture**: ARM64 (aarch64)
**Features**:
- Native Blackwell support
- FLASHINFER attention backend
- Qwen model registry
- CUDA 13.0 compatible

## License

Models are subject to their respective licenses:
- Qwen2.5-Omni: Qwen License
- Qwen3.5: Qwen License
- MOSS-TTS: Apache 2.0

## Support

For issues:
1. Check logs: `docker logs -f qwen-brain`
2. Verify health: `./test_qwen_omni.sh`
3. Check VRAM: `nvidia-smi`
4. Review: `QWEN_OMNI_STACK_GUIDE.md`

---

**Ready to deploy!** Run `./start_qwen_omni_stack.sh` to begin.
