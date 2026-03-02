#!/bin/bash
# Check status of all pipeline components

echo "═══════════════════════════════════════════════════════════════"
echo "  DGX Spark S2S Pipeline - Status Check"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_service() {
    local name=$1
    local url=$2
    local timeout=${3:-3}
    
    if curl -s --max-time $timeout "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✅${NC} $name"
        return 0
    else
        echo -e "${RED}❌${NC} $name"
        return 1
    fi
}

check_tmux() {
    local name=$1
    if tmux has-session -t "$name" 2>/dev/null; then
        echo -e "${GREEN}✅${NC} tmux: $name"
        return 0
    else
        echo -e "${RED}❌${NC} tmux: $name"
        return 1
    fi
}

echo "Services:"
check_service "LiveKit Server" "http://localhost:7880"
check_service "Voxtral ASR" "http://localhost:8001/v1/models"
check_service "Nemotron LLM" "http://localhost:8000/v1/models"
check_service "MOSS-TTS" "http://localhost:8002/health"

echo ""
echo "Tmux Sessions (Persistent Processes):"
check_tmux "livekit-orchestrator"
check_tmux "voxtral-asr"
check_tmux "cloudflared"
check_tmux "livekit-server"

echo ""
echo "GPU Status:"
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null | while read line; do
    echo "  $line"
done

echo ""
echo "External Access (via Cloudflared):"
echo "  LiveKit:  wss://livekit.voiceflow.cloud"
echo "  API:      https://orchestrator.voiceflow.cloud"

echo ""
