# Flow - Testing Guide

Complete testing procedures for the voice AI stack.

## Prerequisites

All four terminals must be running:
- Terminal 1: Nemotron LLM (Port 8000)
- Terminal 2: Voxtral ASR (Port 8001)
- Terminal 3: MOSS-TTS (Port 8002)
- Terminal 4: Rust Orchestrator

## Quick Test

```bash
cd ~/telephony-stack
./scripts/test-full-pipeline.sh
```

This tests:
1. Direct LLM query
2. Direct TTS generation
3. TTS with voice cloning (if reference audio exists)

## Manual Testing

### 1. Test Individual Services

**LLM Test:**
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nvidia/Nemotron-3-Nano-30B",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50,
    "temperature": 0.3
  }'
```

**ASR Test:**
```bash
# Requires audio.wav file
curl -X POST http://localhost:8001/v1/audio/transcriptions \
  -F "file=@audio.wav" \
  -F "model=voxtral"
```

**TTS Test:**
```bash
curl -X POST http://localhost:8002/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
    "input": "Hello from Flow!",
    "response_format": "pcm"
  }' --output test.pcm

# Play audio (requires sox)
play -r 24000 -e signed -b 16 -c 1 test.pcm
```

### 2. Test Voice Cloning

Your reference audio is already configured:
- File: `tts/phil-conversational-16k-5s.wav`
- Format: WAV, Mono, 16kHz, PCM 16-bit, 5 seconds

**Manual voice cloning test:**
```bash
# Encode reference audio
REF_AUDIO_B64=$(base64 -w 0 ~/telephony-stack/tts/phil-conversational-16k-5s.wav)

# Generate speech with your voice
curl -X POST http://localhost:8002/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"OpenMOSS-Team/MOSS-TTS-Realtime\",
    \"input\": \"This is a test of my cloned voice speaking through the AI system.\",
    \"response_format\": \"pcm\",
    \"extra_body\": {
      \"reference_audio\": \"$REF_AUDIO_B64\"
    }
  }" --output cloned_voice.pcm

# Play it
play -r 24000 -e signed -b 16 -c 1 cloned_voice.pcm
```

### 3. Test Orchestrator (Full Pipeline)

The orchestrator connects to Voxtral ASR WebSocket and processes real-time audio.

**WebSocket test:**
```bash
# Install wscat if needed
npm install -g wscat

# Connect to ASR
wscat -c ws://localhost:8001/v1/realtime

# Send audio data (base64 encoded PCM)
> {"type": "audio", "data": "<base64_audio>"}

# Commit after silence
> {"type": "commit"}
```

**Expected flow:**
1. Audio → ASR (WebSocket)
2. ASR text → Rust Orchestrator
3. Orchestrator → Nemotron LLM (HTTP SSE)
4. LLM tokens → buffered into sentences
5. Sentences → MOSS-TTS (HTTP with voice cloning)
6. TTS audio → output

### 4. Performance Monitoring

**GPU Usage:**
```bash
watch -n 1 nvidia-smi
```

**Service Health:**
```bash
# Check all services
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
```

**Orchestrator Logs:**
```bash
# In Terminal 4, you should see:
# - "✓ Nemotron LLM (Port 8000)"
# - "✓ Voxtral ASR (Port 8001)"
# - "✓ MOSS-TTS (Port 8002)"
# - "Voice: Using zero-shot voice cloning"
```

## Expected Latencies

| Step | Target | Notes |
|------|--------|-------|
| ASR First Interim | <200ms | Initial transcription |
| ASR Final | <500ms | Complete utterance |
| LLM TTFT | <100ms | Time to first token |
| LLM TPS | >20 | Tokens per second |
| TTS Latency | <200ms | First audio chunk |
| **Total E2E** | **<500ms** | User speaks → hears response |

## Troubleshooting

### Orchestrator can't connect to services
```bash
# Check if ports are listening
ss -tlnp | grep -E "8000|8001|8002"

# Restart services if needed
./scripts/start-nemotron.sh      # Terminal 1
./scripts/start-voxtral-asr.sh   # Terminal 2
./scripts/start-moss-tts-native.sh  # Terminal 3
```

### Voice cloning not working
```bash
# Verify reference audio exists
ls -lh ~/telephony-stack/tts/phil-conversational-16k-5s.wav

# Check file format
file ~/telephony-stack/tts/phil-conversational-16k-5s.wav
# Should show: RIFF (little-endian) data, WAVE audio, Microsoft PCM, 16 bit, mono 16000 Hz
```

### No audio output
```bash
# Install sox for audio playback
sudo apt-get install sox libsox-fmt-all

# Test PCM playback
play -r 24000 -e signed -b 16 -c 1 test.pcm
```

## Next Steps for Full Integration

1. **LiveKit SIP**: Connect to telephony provider
2. **Audio I/O**: Implement actual audio capture/playback in orchestrator
3. **Call State**: Manage multiple concurrent calls
4. **Monitoring**: Add metrics and logging

## Files Reference

```
~/telephony-stack/
├── scripts/
│   └── test-full-pipeline.sh    # Automated tests
├── tts/
│   └── phil-conversational-16k-5s.wav  # Your cloned voice
└── TESTING.md                   # This file
```
