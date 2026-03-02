#!/bin/bash
# Production startup script for DGX Spark S2S Pipeline
# Sets up persistent services using tmux

set -e

cd "$(dirname "$0")"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  DGX Spark S2S Pipeline - Production Startup${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Function to check if tmux session exists
session_exists() {
    tmux has-session -t "$1" 2>/dev/null
}

# Function to create or attach to tmux session
ensure_session() {
    local name=$1
    local command=$2
    local dir=${3:-$(pwd)}
    
    if session_exists "$name"; then
        echo -e "${YELLOW}  ⚠️  Session '$name' already exists${NC}"
        echo "      Attach with: tmux attach -t $name"
    else
        echo -e "${GREEN}  ✅ Creating session '$name'${NC}"
        tmux new-session -d -s "$name" -c "$dir"
        tmux send-keys -t "$name" "$command" C-m
        echo "      Attach with: tmux attach -t $name"
    fi
}

# 1. Check LiveKit Server
echo ""
echo -e "${BLUE}[1/5] LiveKit Server${NC}"
if curl -s http://localhost:7880 > /dev/null 2>&1; then
    echo -e "${GREEN}  ✅ Already running on port 7880${NC}"
else
    echo "  Starting LiveKit..."
    cd livekit-server
    ensure_session "livekit-server" "docker compose up" "$(pwd)"
    cd ..
    sleep 2
fi

# 2. Check Voxtral ASR
echo ""
echo -e "${BLUE}[2/5] Voxtral ASR${NC}"
if curl -s http://localhost:8001/v1/models > /dev/null 2>&1; then
    echo -e "${GREEN}  ✅ Already running on port 8001${NC}"
else
    echo "  Starting Voxtral ASR..."
    ensure_session "voxtral-asr" "source ~/telephony-stack-env/bin/activate && export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas && export HF_HOME=\"\$HOME/telephony-stack/models/hf_cache\" && python3 -m vllm.entrypoints.openai.api_server --model mistralai/Voxtral-Mini-4B-Realtime-2602 --trust-remote-code --dtype bfloat16 --gpu-memory-utilization 0.15 --max-model-len 4096 --enforce-eager --port 8001"
fi

# 3. Check Nemotron LLM
echo ""
echo -e "${BLUE}[3/5] Nemotron LLM${NC}"
if curl -s http://localhost:8000/v1/models > /dev/null 2>&1; then
    echo -e "${GREEN}  ✅ Already running on port 8000${NC}"
else
    echo -e "${YELLOW}  ⚠️  Nemotron LLM not running${NC}"
    echo "      Start manually if needed"
fi

# 4. Check MOSS-TTS
echo ""
echo -e "${BLUE}[4/5] MOSS-TTS${NC}"
if curl -s http://localhost:8002/health > /dev/null 2>&1; then
    echo -e "${GREEN}  ✅ Already running on port 8002${NC}"
else
    echo -e "${YELLOW}  ⚠️  MOSS-TTS not running${NC}"
    echo "      Start manually if needed"
fi

# 5. Start Rust Orchestrator (ALWAYS restart this one for fresh connections)
echo ""
echo -e "${BLUE}[5/5] Rust LiveKit Orchestrator${NC}"
if session_exists "livekit-orchestrator"; then
    echo -e "${YELLOW}  ⚠️  Session exists - restarting...${NC}"
    tmux kill-session -t "livekit-orchestrator" 2>/dev/null || true
    sleep 1
fi

echo "  Starting Rust Orchestrator..."
cd livekit_orchestrator
ensure_session "livekit-orchestrator" "./start.sh" "$(pwd)"
cd ..

# 6. Start/Restart Cloudflared
echo ""
echo -e "${BLUE}[6/6] Cloudflared Tunnel${NC}"
if session_exists "cloudflared"; then
    echo -e "${GREEN}  ✅ Cloudflared already running${NC}"
    echo "      Restart to apply new config: tmux kill-session -t cloudflared && ./start_production.sh"
else
    echo "  Starting Cloudflared..."
    ensure_session "cloudflared" "cloudflared tunnel --config ~/.cloudflared/config.yml run"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Production Pipeline Started!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Active tmux sessions:"
tmux list-sessions 2>/dev/null || echo "  (none)"
echo ""
echo "View logs:"
echo "  tmux attach -t livekit-orchestrator"
echo "  tmux attach -t voxtral-asr"
echo "  tmux attach -t cloudflared"
echo ""
echo "External URLs:"
echo "  LiveKit:  wss://livekit.voiceflow.cloud"
echo "  HTTP API: https://orchestrator.voiceflow.cloud"
echo ""
echo "To attach to a session:"
echo "  tmux attach -t <session-name>"
echo ""
echo "To detach from tmux (keep running):"
echo "  Press Ctrl+B, then D"
echo ""
