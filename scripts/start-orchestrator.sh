#!/bin/bash
# =============================================================================
# Start Flow Telephony Orchestrator (Rust)
# =============================================================================

set -e

cd ~/telephony-stack

# Source cargo environment
source "$HOME/.cargo/env"

# Environment configuration
export CUDA_HOME=/usr/local/cuda-13.0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME="${HF_HOME:-$HOME/telephony-stack/.cache/huggingface}"

# VAD model path (must be absolute)
export VAD_MODEL_PATH="$HOME/telephony-stack/orchestrator/models/silero_vad.onnx"

# Voice cloning reference audio (WAV, Mono, 16kHz, PCM 16-bit, 3-5 seconds)
# Converted from MP3 using: librosa.load(..., sr=16000, mono=True)
export TTS_VOICE_FILE="$HOME/telephony-stack/tts/phil-conversational-16k-5s.wav"

# Backend URLs (adjust if needed)
export ASR_WS_URL="${ASR_WS_URL:-ws://127.0.0.1:8001/v1/realtime}"
export LLM_URL="${LLM_URL:-http://127.0.0.1:8000/v1/chat/completions}"
export TTS_URL="${TTS_URL:-http://127.0.0.1:8002/v1/audio/speech}"

# Logging
export RUST_LOG="${RUST_LOG:-info}"

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Starting Flow Telephony Orchestrator                              ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Configuration:"
echo "  ASR WebSocket: $ASR_WS_URL"
echo "  LLM HTTP:      $LLM_URL"
echo "  TTS HTTP:      $TTS_URL"
echo "  VAD Model:     $VAD_MODEL_PATH"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run the orchestrator from its directory
export VAD_MODEL_PATH="$HOME/telephony-stack/orchestrator/models/silero_vad.onnx"
cd orchestrator
exec ./target/release/telephony-orchestrator
