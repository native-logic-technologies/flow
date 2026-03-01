#!/bin/bash
# =============================================================================
# Download Nemotron-3-Nano-30B-A3B-NVFP4 (Mamba-MoE)
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Downloading Nemotron-3-Nano-30B-A3B-NVFP4                      ║"
echo "║     (Mamba-MoE, no KV cache needed)                                ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    source "$HOME/telephony-stack-env/bin/activate" 2>/dev/null || {
        echo -e "${RED}Error: Not in virtual environment${NC}"
        exit 1
    }
fi

MODEL_DIR="$HOME/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4"
MODEL_ID="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4"

echo -e "${BLUE}Target directory: ${MODEL_DIR}${NC}"
echo ""

# Check if already downloaded
if [ -d "$MODEL_DIR" ] && [ "$(ls -A $MODEL_DIR)" ]; then
    echo -e "${YELLOW}Model directory already exists and has content${NC}"
    echo "Files: $(ls $MODEL_DIR | wc -l)"
    read -p "Re-download? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Using existing model"
        exit 0
    fi
    rm -rf "$MODEL_DIR"
fi

mkdir -p "$MODEL_DIR"

# Check for HF token
if [ -z "$HF_TOKEN" ]; then
    echo -e "${YELLOW}HF_TOKEN not set${NC}"
    echo "Please set it with: export HF_TOKEN=your_token"
    echo "Or enter it now:"
    read -s HF_TOKEN
    export HF_TOKEN
fi

echo -e "${BLUE}Downloading model (this may take 30-60 minutes)...${NC}"
echo "Model: $MODEL_ID"
echo ""

huggingface-cli download \
    "$MODEL_ID" \
    --local-dir "$MODEL_DIR" \
    --local-dir-use-symlinks False \
    --resume-download \
    --token "$HF_TOKEN"

echo ""
echo -e "${BLUE}Verifying download...${NC}"

# Check for key files
if [ -f "$MODEL_DIR/config.json" ]; then
    echo "✓ config.json found"
    # Show model info
    python3 << PYEOF
import json
with open("$MODEL_DIR/config.json") as f:
    config = json.load(f)
print(f"Model type: {config.get('model_type', 'unknown')}")
print(f"Architecture: Mamba-MoE (no KV cache)")
PYEOF
else
    echo -e "${RED}✗ config.json not found${NC}"
    exit 1
fi

# Check for model weights
WEIGHT_COUNT=$(find "$MODEL_DIR" -name "*.safetensors" -o -name "*.bin" | wc -l)
if [ "$WEIGHT_COUNT" -gt 0 ]; then
    echo "✓ Model weights found: $WEIGHT_COUNT files"
else
    echo -e "${YELLOW}⚠ No model weights found (may still be downloading)${NC}"
fi

echo ""
echo -e "${GREEN}✓ Nemotron model ready at: ${MODEL_DIR}${NC}"
echo ""
echo "Next step: ./04-test-nemotron.sh"
