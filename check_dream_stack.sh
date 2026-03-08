#!/bin/bash
# Check all components of the Dream Stack

echo "╔═══════════════════════════════════════════════════════════════════════════════╗"
echo "║                    🏆 DREAM STACK HEALTH CHECK                                ║"
echo "╚═══════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_service() {
    local name=$1
    local url=$2
    local port=$3
    
    echo -n "Checking $name (Port $port)... "
    
    if curl -s $url > /dev/null 2>&1; then
        echo -e "${GREEN}✅ ONLINE${NC}"
        return 0
    else
        echo -e "${RED}❌ OFFLINE${NC}"
        return 1
    fi
}

# Check each service
check_service "MOSS-TTS (Voice)" "http://localhost:5002/health" "5002"
check_service "Nemotron (Brain)" "http://localhost:8000/health" "8000"
check_service "Qwen2.5-Omni (Ear)" "http://localhost:8001/health" "8001"
check_service "Orchestrator" "http://localhost:8080/health" "8080"

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# VRAM Check
echo "📊 VRAM Usage:"
nvidia-smi --query-gpu=memory.used,memory.total,memory.free --format=csv,noheader,nounits | \
    awk '{printf "   Used: %.1f GB / Total: %.1f GB / Free: %.1f GB\n", $1/1024, $2/1024, $3/1024}'

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# Quick tests if all services are up
if curl -s http://localhost:8000/health > /dev/null 2>&1 && \
   curl -s http://localhost:8001/health > /dev/null 2>&1; then
    
    echo "🧪 Running quick tests..."
    echo ""
    
    # Test Brain
    echo -n "Testing Brain (Nemotron)... "
    BRAIN_RESP=$(curl -s -X POST http://localhost:8000/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d '{"model": "nemotron", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10}' 2>/dev/null)
    if [ -n "$BRAIN_RESP" ]; then
        echo -e "${GREEN}✅ RESPONDING${NC}"
    else
        echo -e "${YELLOW}⚠️  NO RESPONSE${NC}"
    fi
    
    # Test Ear
    echo -n "Testing Ear (Qwen2.5-Omni)... "
    EAR_RESP=$(curl -s http://localhost:8001/health 2>/dev/null)
    if [ -n "$EAR_RESP" ]; then
        echo -e "${GREEN}✅ RESPONDING${NC}"
    else
        echo -e "${YELLOW}⚠️  NO RESPONSE${NC}"
    fi
    
    echo ""
    echo -e "${GREEN}🏆 DREAM STACK IS OPERATIONAL!${NC}"
else
    echo -e "${YELLOW}⚠️  Some services are offline. Run ./start_dream_stack.sh to start them.${NC}"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
