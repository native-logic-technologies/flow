#!/bin/bash
# Start the LiveKit Token Server

cd "$(dirname "$0")"

# Check if we're in the right environment
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install fastapi uvicorn pyjwt -q
fi

# Set environment
export LIVEKIT_API_KEY="${LIVEKIT_API_KEY:-APIQp4vjmCjrWQ9}"
export LIVEKIT_API_SECRET="${LIVEKIT_API_SECRET:-PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l}"
export LIVEKIT_URL="${LIVEKIT_URL:-wss://cleans2s.voiceflow.cloud}"

echo "=================================="
echo "LiveKit Token Server"
echo "=================================="
echo "Port: 8080"
echo "Endpoint: POST /api/token"
echo "LiveKit URL: $LIVEKIT_URL"
echo "=================================="

exec python3 token_api.py "$@"
