#!/bin/bash
# Start the complete DGX Spark S2S Pipeline

set -e

echo "═══════════════════════════════════════════════════════════════"
echo "  DGX Spark S2S Pipeline - Full Stack Startup"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

cd "$(dirname "$0")"

# 1. Check LiveKit Server
echo -e "${BLUE}[1/4] Checking LiveKit Server...${NC}"
if curl -s http://localhost:7880 > /dev/null 2>&1; then
    echo -e "${GREEN}    ✅ LiveKit Server is running on port 7880${NC}"
else
    echo "    Starting LiveKit Server..."
    cd livekit-server
    docker compose up -d
    cd ..
    sleep 3
    echo -e "${GREEN}    ✅ LiveKit Server started${NC}"
fi

# 2. Check Voxtral ASR
echo -e "${BLUE}[2/4] Checking Voxtral ASR...${NC}"
if curl -s http://localhost:8001/v1/models > /dev/null 2>&1; then
    echo -e "${GREEN}    ✅ Voxtral ASR is running on port 8001${NC}"
else
    echo "    ⚠️  Voxtral ASR not running. Start manually with:"
    echo "       ./asr/start_voxtral_vllm.sh"
fi

# 3. Check Nemotron LLM
echo -e "${BLUE}[3/4] Checking Nemotron LLM...${NC}"
if curl -s http://localhost:8000/v1/models > /dev/null 2>&1; then
    echo -e "${GREEN}    ✅ Nemotron LLM is running on port 8000${NC}"
else
    echo "    ⚠️  Nemotron LLM not running. Start manually."
fi

# 4. Check MOSS-TTS
echo -e "${BLUE}[4/4] Checking MOSS-TTS...${NC}"
if curl -s http://localhost:8002/health > /dev/null 2>&1; then
    echo -e "${GREEN}    ✅ MOSS-TTS is running on port 8002${NC}"
else
    echo "    ⚠️  MOSS-TTS not running. Start manually."
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Stack Status"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Check if Rust orchestrator is running
if pgrep -f "livekit_orchestrator" > /dev/null; then
    echo -e "${GREEN}🎉 Rust Orchestrator is RUNNING${NC}"
    echo ""
    echo "The S2S pipeline is fully operational!"
    echo "Connect a LiveKit client to ws://localhost:7880"
else
    echo "🚀 Ready to start Rust Orchestrator:"
    echo ""
    echo "   cd livekit_orchestrator && ./start.sh"
    echo ""
fi

echo "═══════════════════════════════════════════════════════════════"
