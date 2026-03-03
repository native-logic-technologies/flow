#!/bin/bash
#
# Deploy Token-Level Streaming S2S Pipeline
# Achieves <500ms E2E latency by streaming tokens from LLM to TTS immediately
#

set -e

echo "=============================================="
echo "Token-Level Streaming S2S Deployment"
echo "=============================================="
echo ""
echo "This deployment enables true waterfall streaming:"
echo "  LLM token -> Rust sends immediately -> TTS processes -> Audio chunk"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check services are running
echo -e "${YELLOW}Checking services...${NC}"

# Check LLM (Nemotron)
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} LLM service (Nemotron) on port 8000"
else
    echo -e "${RED}✗${NC} LLM service not responding on port 8000"
    echo "  Start with: sudo systemctl start nemotron-9b-vllm"
    exit 1
fi

# Check ASR (Voxtral)
if curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} ASR service (Voxtral) on port 8001"
else
    echo -e "${RED}✗${NC} ASR service not responding on port 8001"
    echo "  Start with: sudo systemctl start voxtral-asr"
    exit 1
fi

# Check TTS (MOSS-TTS)
if curl -s http://localhost:8002/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} TTS service (MOSS-TTS) on port 8002"
else
    echo -e "${RED}✗${NC} TTS service not responding on port 8002"
    echo "  Start with: sudo systemctl start moss-tts-server"
    exit 1
fi

# Check LiveKit
cd ~/telephony-stack/livekit-server
if docker compose ps | grep -q "livekit.*Up"; then
    echo -e "${GREEN}✓${NC} LiveKit server running"
else
    echo -e "${YELLOW}!${NC} LiveKit server not running, starting..."
    docker compose up -d
    sleep 3
fi

echo ""
echo -e "${YELLOW}Building Rust orchestrator with token-level streaming...${NC}"
cd ~/telephony-stack/livekit_orchestrator
cargo build --release 2>&1 | tail -5

if [ ! -f target/release/livekit_orchestrator ]; then
    echo -e "${RED}Build failed!${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Build successful"
echo ""

# Kill any existing orchestrator
echo -e "${YELLOW}Stopping any existing orchestrator...${NC}"
pkill -f livekit_orchestrator || true
sleep 1

echo ""
echo "=============================================="
echo -e "${GREEN}Starting Token-Level Streaming Orchestrator${NC}"
echo "=============================================="
echo ""
echo "Streaming configuration:"
echo "  - FLUSH_SIZE: 25 chars (Comma-Level Chunking - "Golden Ratio")"
echo "  - FLUSH_TIMEOUT: 30ms (or flush after 30ms)"
echo "  - Protocol: {\"type\": \"token\", \"text\": \"...\"}"
echo ""
echo "Expected latency improvement:"
echo "  - Before: ~6000ms (batching sentences)"
echo "  - After: ~400-500ms (token-level streaming)"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run the orchestrator with token-level streaming
export RUST_LOG=info
export LLM_URL=http://localhost:8000
export ASR_URL=http://localhost:8001
export TTS_URL=ws://localhost:8002
export LIVEKIT_WS_URL=ws://localhost:7880
export ROOM_NAME=dgx-spark-room

exec ./target/release/livekit_orchestrator
