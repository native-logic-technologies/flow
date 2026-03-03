#!/bin/bash
# LiveKit Telephony Agent Dispatcher
# Auto-configured for: 6aii08srz2e.sip.livekit.cloud

# LiveKit Cloud credentials
export LIVEKIT_URL="wss://6aii08srz2e.livekit.cloud"
export LIVEKIT_API_KEY="${LIVEKIT_API_KEY:-APIQp4vjmCjrWQ9}"
export LIVEKIT_API_SECRET="${LIVEKIT_API_SECRET:-PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l}"

# AI Service URLs (local DGX Spark)
export ASR_URL="${ASR_URL:-http://localhost:8001}"
export LLM_URL="${LLM_URL:-http://localhost:8000}"
export TTS_URL="${TTS_URL:-ws://localhost:8002}"

# Path to orchestrator binary
ORCHESTRATOR_BIN="${ORCHESTRATOR_BIN:-$HOME/telephony-stack/livekit_orchestrator/target/release/livekit_orchestrator}"
LIB_PATH="${LIB_PATH:-$HOME/telephony-stack/livekit_orchestrator/lib}"

# Room prefix for telephony calls
ROOM_PREFIX="${ROOM_PREFIX:-call-}"

# Max concurrent calls (based on VRAM: ~500 for 128GB)
MAX_CALLS="${MAX_CALLS:-500}"

echo "═══════════════════════════════════════════════════════════"
echo "  DGX SPARK TELEPHONY AGENT"
echo "  SIP: sip:6aii08srz2e.sip.livekit.cloud"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Configuration:"
echo "  LiveKit URL: $LIVEKIT_URL"
echo "  Room Prefix: $ROOM_PREFIX"
echo "  Max Calls: $MAX_CALLS"
echo ""

# Set library path
export LD_LIBRARY_PATH="$LIB_PATH:$LD_LIBRARY_PATH"

# Check if orchestrator binary exists
if [ ! -f "$ORCHESTRATOR_BIN" ]; then
    echo "❌ Orchestrator binary not found: $ORCHESTRATOR_BIN"
    exit 1
fi

# Function to spawn agent for a specific room
spawn_agent() {
    local room_name=$1
    local agent_id="agent-${room_name}"
    
    export ROOM_NAME="$room_name"
    
    echo "📞 Joining room: $room_name"
    
    # Run orchestrator
    "$ORCHESTRATOR_BIN" 2>&1 | while read line; do
        echo "[$room_name] $line"
    done &
}

# Count active calls
count_active_calls() {
    ps aux | grep "livekit_orchestrator" | grep -v grep | wc -l
}

# Single call mode - join specific room
room="${1:-${ROOM_PREFIX}test}"
echo "🎯 Joining room '$room'"
echo "   (Call your Twilio number to test)"
echo ""
spawn_agent "$room"
wait
