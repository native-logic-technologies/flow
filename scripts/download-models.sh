#!/bin/bash
# =============================================================================
# Download LLM and ASR models
# =============================================================================

set -e

source ~/telephony-stack-env/bin/activate

export HF_HOME=~/telephony-stack/.cache/huggingface

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Downloading Models                                                ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check HF_TOKEN
if [ -z "$HF_TOKEN" ]; then
    echo -e "${RED}Error: HF_TOKEN not set${NC}"
    echo "Set with: export HF_TOKEN=your_token_here"
    exit 1
fi

mkdir -p ~/telephony-stack/models/{llm,asr}

# Download Nemotron
echo -e "${BLUE}Downloading Nemotron-3-Nano-30B-A3B-NVFP4...${NC}"
echo "Size: ~19 GB"
echo "This will take 30-60 minutes..."
echo ""

huggingface-cli download \
    nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
    --local-dir ~/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4 \
    --local-dir-use-symlinks False \
    --token "$HF_TOKEN"

echo -e "${GREEN}✓ Nemotron downloaded${NC}"
echo ""

# Download Voxtral
echo -e "${BLUE}Downloading Voxtral-Mini-4B-Realtime-2602...${NC}"
echo "Size: ~17 GB"
echo "This will take 20-40 minutes..."
echo ""

huggingface-cli download \
    mistralai/Voxtral-Mini-4B-Realtime-2602 \
    --local-dir ~/telephony-stack/models/asr/voxtral-mini-4b-realtime \
    --local-dir-use-symlinks False

echo -e "${GREEN}✓ Voxtral downloaded${NC}"
echo ""

# Verify
echo "Verifying downloads..."
echo ""
echo "Nemotron:"
ls -lh ~/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4/*.safetensors 2>/dev/null | wc -l | xargs echo "  Safetensors files:"
du -sh ~/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4/

echo ""
echo "Voxtral:"
ls -lh ~/telephony-stack/models/asr/voxtral-mini-4b-realtime/*.safetensors 2>/dev/null | wc -l | xargs echo "  Safetensors files:"
du -sh ~/telephony-stack/models/asr/voxtral-mini-4b-realtime/

echo ""
echo -e "${GREEN}✅ All models downloaded!${NC}"
