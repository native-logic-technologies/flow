#!/bin/bash
# LiveKit Cloud Telephony Agent
# IMPORTANT: Update LIVEKIT_API_KEY and LIVEKIT_API_SECRET with your LiveKit Cloud credentials!

set -e

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║     DGX SPARK + LIVEKIT CLOUD TELEPHONY SYSTEM               ║"
echo "║     SIP: sip:6aii08srz2e.sip.livekit.cloud                   ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# ⚠️  UPDATE THESE with your LiveKit Cloud credentials from https://cloud.livekit.io
# Project Settings → API Keys
default_api_key="APIQp4vjmCjrWQ9"  # REPLACE WITH CLOUD API KEY
default_api_secret="PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l"  # REPLACE WITH CLOUD API SECRET

# Check if using placeholder credentials
if [ -z "${LIVEKIT_CLOUD_API_KEY}" ]; then
    echo "⚠️  WARNING: Using placeholder API credentials!"
    echo "   Get your LiveKit Cloud credentials:"
    echo "   1. Go to https://cloud.livekit.io"
    echo "   2. Project Settings → API Keys"
    echo "   3. Set environment variables:"
    echo "      export LIVEKIT_CLOUD_API_KEY='your-cloud-api-key'"
    echo "      export LIVEKIT_CLOUD_API_SECRET='your-cloud-api-secret'"
    echo ""
    export LIVEKIT_API_KEY="${LIVEKIT_API_KEY:-$default_api_key}"
    export LIVEKIT_API_SECRET="${LIVEKIT_API_SECRET:-$default_api_secret}"
else
    export LIVEKIT_API_KEY="${LIVEKIT_CLOUD_API_KEY}"
    export LIVEKIT_API_SECRET="${LIVEKIT_CLOUD_API_SECRET}"
fi

# LiveKit Cloud Configuration
export LIVEKIT_WS_URL="wss://6aii08srz2e.livekit.cloud"

# AI Services (local DGX)
export ASR_URL="http://localhost:8001"
export LLM_URL="http://localhost:8000"
export TTS_URL="ws://localhost:8002"

# Orchestrator
export ORCHESTRATOR_BIN="$HOME/telephony-stack/livekit_orchestrator/target/release/livekit_orchestrator"
export LD_LIBRARY_PATH="$HOME/telephony-stack/livekit_orchestrator/lib:$LD_LIBRARY_PATH"

# Room name for telephony
export ROOM_NAME="${1:-call-test}"

echo "📡 Connecting to LiveKit Cloud: $LIVEKIT_WS_URL"
echo "📞 Room: $ROOM_NAME"
echo "🔑 API Key: ${LIVEKIT_API_KEY:0:10}..."
echo ""

# Check orchestrator exists
if [ ! -f "$ORCHESTRATOR_BIN" ]; then
    echo "❌ Orchestrator not found: $ORCHESTRATOR_BIN"
    exit 1
fi

echo "🚀 Starting agent... (Press Ctrl+C to stop)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Run orchestrator
exec "$ORCHESTRATOR_BIN"
