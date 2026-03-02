#!/bin/bash
# Start the LiveKit S2S Orchestrator

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Set library path for livekit-ffi
export LD_LIBRARY_PATH="$SCRIPT_DIR/lib:$LD_LIBRARY_PATH"

# Load environment
export LIVEKIT_API_KEY="${LIVEKIT_API_KEY:-APIQp4vjmCjrWQ9}"
export LIVEKIT_API_SECRET="${LIVEKIT_API_SECRET:-PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l}"
export LIVEKIT_WS_URL="${LIVEKIT_WS_URL:-ws://localhost:7880}"
export ROOM_NAME="${ROOM_NAME:-dgx-spark-room}"

# Service endpoints
export LLM_URL="${LLM_URL:-http://localhost:8000}"
export ASR_URL="${ASR_URL:-http://localhost:8001}"
export TTS_URL="${TTS_URL:-ws://localhost:8002}"

# Logging
export RUST_LOG="${RUST_LOG:-info}"

echo "=== LiveKit S2S Orchestrator ==="
echo "LiveKit Server: $LIVEKIT_WS_URL"
echo "Room: $ROOM_NAME"
echo "LLM: $LLM_URL"
echo "ASR: $ASR_URL"
echo "TTS: $TTS_URL"
echo "=================================="

# Run the orchestrator
exec ./target/release/livekit_orchestrator "$@"
