#!/bin/bash
# Multi-Room Agent Dispatcher for LiveKit Cloud
# Handles both Web (dgx-demo-room) and Phone calls (call-*) simultaneously

set -e

# LiveKit Cloud Credentials
export LIVEKIT_API_KEY="${LIVEKIT_CLOUD_API_KEY:-APIgJ2YDbVw8FBJ}"
export LIVEKIT_API_SECRET="${LIVEKIT_CLOUD_API_SECRET:-LRaZKuC3ou2JcjDMRic34k9gzSn1V44uIAm2AcERNee}"
export LIVEKIT_WS_URL="${LIVEKIT_WS_URL:-wss://ari-7m62wwj7.livekit.cloud}"

# AI Services
export ASR_URL="http://localhost:8001"
export LLM_URL="http://localhost:8000"
export TTS_URL="ws://localhost:8002"

# Paths
ORCHESTRATOR_BIN="$HOME/telephony-stack/livekit_orchestrator/target/release/livekit_orchestrator"
LIB_PATH="$HOME/telephony-stack/livekit_orchestrator/lib"
export LD_LIBRARY_PATH="$LIB_PATH:$LD_LIBRARY_PATH"

# Rooms to monitor
WEB_ROOM="dgx-demo-room"
PHONE_ROOM_PREFIX="call-"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           DGX SPARK MULTI-AGENT DISPATCHER                     ║"
echo "║        (Web + Phone Simultaneously)                           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "LiveKit Cloud: $LIVEKIT_WS_URL"
echo "SIP URI: sip:ari-7m62wwj7.sip.livekit.cloud"
echo ""

# Check orchestrator exists
if [ ! -f "$ORCHESTRATOR_BIN" ]; then
    echo "❌ Orchestrator not found at $ORCHESTRATOR_BIN"
    exit 1
fi

# Function to spawn worker for a room
spawn_worker() {
    local room=$1
    local logfile="/tmp/orchestrator-${room}.log"
    
    # Check if already running
    if pgrep -f "livekit_orchestrator.*$room" > /dev/null; then
        echo "   ℹ️  Worker for '$room' already running"
        return
    fi
    
    echo "   🚀 Spawning worker for room: $room"
    
    # Spawn in background
    (
        export ROOM_NAME="$room"
        export LIVEKIT_API_KEY
        export LIVEKIT_API_SECRET
        export LIVEKIT_WS_URL
        export LD_LIBRARY_PATH
        cd "$HOME/telephony-stack/livekit_orchestrator"
        exec "$ORCHESTRATOR_BIN" > "$logfile" 2>&1
    ) &
}

# Kill existing orchestrators
echo "🧹 Cleaning up old workers..."
pkill -9 -f "livekit_orchestrator" 2>/dev/null || true
sleep 2

# Spawn workers
echo ""
echo "📡 Spawning workers..."
spawn_worker "$WEB_ROOM"
spawn_worker "${PHONE_ROOM_PREFIX}test"

echo ""
echo "✅ Workers spawned!"
echo ""
echo "Handling:"
echo "  • Web: https://flow.speak.ad (room: $WEB_ROOM)"
echo "  • Phone: Call your Twilio number (room: ${PHONE_ROOM_PREFIX}*)"
echo ""
echo "📊 Monitor with:"
echo "  tail -f /tmp/orchestrator-${WEB_ROOM}.log"
echo "  tail -f /tmp/orchestrator-${PHONE_ROOM_PREFIX}test.log"
echo ""
echo "Press Ctrl+C to stop all workers"
echo ""

# Keep script running
while true; do
    sleep 5
    
    # Check if workers are still alive
    if ! pgrep -f "livekit_orchestrator" > /dev/null; then
        echo "❌ All workers died!"
        exit 1
    fi
    
    # Show status
    active=$(pgrep -c "livekit_orchestrator" || echo "0")
    echo "$(date '+%H:%M:%S') - Active workers: $active"
done
