#!/bin/bash
# =============================================================================
# Fix vLLM CUDA 13.0 Compatibility
# Compile vLLM from source for CUDA 13.0 / sm_121
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Fixing vLLM CUDA 13.0 Compatibility                            ║"
echo "║     (Compile from source for sm_121)                               ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source "$HOME/telephony-stack-env/bin/activate" 2>/dev/null || {
        echo -e "${RED}Error: Virtual environment not found${NC}"
        exit 1
    }
fi

# Set CUDA environment
export CUDA_HOME=/usr/local/cuda-13.0
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export TORCH_CUDA_ARCH_LIST="12.1"

echo -e "${BLUE}Environment:${NC}"
echo "  CUDA_HOME: $CUDA_HOME"
echo "  LD_LIBRARY_PATH: $LD_LIBRARY_PATH"
echo "  TORCH_CUDA_ARCH_LIST: $TORCH_CUDA_ARCH_LIST"
echo ""

# Uninstall pre-built vLLM
echo -e "${BLUE}Removing pre-built vLLM...${NC}"
pip uninstall -y vllm 2>/dev/null || true

# Install build dependencies
echo -e "${BLUE}Installing build dependencies...${NC}"
pip install --upgrade pip
pip install ninja packaging setuptools wheel cmake

# Clone and build vLLM from source
VLLM_DIR="$HOME/vllm-src"

echo ""
echo -e "${BLUE}Cloning vLLM source...${NC}"

if [ -d "$VLLM_DIR" ]; then
    echo "Existing vLLM source found, updating..."
    cd "$VLLM_DIR"
    git fetch origin
    git reset --hard origin/main 2>/dev/null || git reset --hard origin/master 2>/dev/null || true
else
    git clone https://github.com/vllm-project/vllm.git "$VLLM_DIR"
    cd "$VLLM_DIR"
fi

# Checkout a stable version with Mamba support
echo ""
echo -e "${BLUE}Checking out stable version...${NC}"
git checkout v0.11.0 2>/dev/null || git checkout main

echo ""
echo -e "${BLUE}Building vLLM from source (this takes 30-60 minutes)...${NC}"
echo ""

# Clean any previous builds
rm -rf build dist *.egg-info

# Build with CUDA 13.0 / sm_121 support
pip install -e . \
    --no-build-isolation \
    -v 2>&1 | tee /tmp/vllm-build.log

echo ""
echo -e "${BLUE}Verifying vLLM installation...${NC}"

python3 << 'PYEOF'
import os
os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"
os.environ["CUDA_HOME"] = "/usr/local/cuda-13.0"

import torch
import vllm

print(f"PyTorch: {torch.__version__}")
print(f"CUDA: {torch.version.cuda}")
print(f"vLLM: {vllm.__version__}")
print(f"CUDA Available: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"Device: {torch.cuda.get_device_name(0)}")
    
    # Test vLLM import
    from vllm import LLM, SamplingParams
    print("✓ vLLM imports successful with CUDA 13.0")
else:
    print("✗ CUDA not available")
    exit(1)
PYEOF

echo ""
echo -e "${GREEN}✓ vLLM compiled successfully for CUDA 13.0!${NC}"
echo ""
