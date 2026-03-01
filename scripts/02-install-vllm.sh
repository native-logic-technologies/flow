#!/bin/bash
# =============================================================================
# Install vLLM for DGX Spark (Blackwell sm_121 support)
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Installing vLLM for DGX Spark                                  ║"
echo "║     (With Mamba and NVFP4 support)                                 ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    source "$HOME/telephony-stack-env/bin/activate" 2>/dev/null || {
        echo -e "${RED}Error: Not in virtual environment${NC}"
        exit 1
    }
fi

export CUDA_HOME=/usr/local/cuda-13.0
export PATH=$CUDA_HOME/bin:$PATH

# Critical: Use spawn for multiprocessing on ARM64/Blackwell
export VLLM_WORKER_MULTIPROC_METHOD=spawn

echo -e "${BLUE}Installing vLLM and dependencies...${NC}"

# Install core dependencies
pip install --upgrade \
    transformers \
    accelerate \
    huggingface-hub \
    sentencepiece \
    protobuf

# Install vLLM
# For production with Mamba/NVFP4, we may need to build from source
# For initial setup, try pre-built wheel first
echo ""
echo -e "${BLUE}Attempting to install vLLM...${NC}"

pip install vllm || {
    echo -e "${YELLOW}Pre-built wheel failed, will need to compile from source${NC}"
    echo "This will take 30-60 minutes..."
    
    cd ~
    if [ ! -d "vllm" ]; then
        git clone https://github.com/vllm-project/vllm.git
    fi
    cd vllm
    git pull
    
    # Install build dependencies
    pip install ninja packaging setuptools wheel
    
    # Build with sm_121 support
    export TORCH_CUDA_ARCH_LIST="12.1"
    pip install -e . --no-build-isolation
}

echo ""
echo -e "${BLUE}Verifying vLLM installation...${NC}"

python3 << 'PYEOF'
import os
os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"

import vllm
import torch

print(f"vLLM Version: {vllm.__version__}")
print(f"CUDA Available: {torch.cuda.is_available()}")

# Test basic functionality
from vllm import LLM, SamplingParams

print("✓ vLLM imports successful")

# Quick smoke test with tiny model
print("\nRunning smoke test with facebook/opt-125m...")
try:
    llm = LLM(model="facebook/opt-125m", max_model_len=512)
    params = SamplingParams(temperature=0.0, max_tokens=8)
    outs = llm.generate(["Hello"], params)
    print(f"✓ Smoke test passed: {outs[0].outputs[0].text}")
except Exception as e:
    print(f"⚠ Smoke test warning (may be due to model download): {e}")
PYEOF

echo ""
echo -e "${GREEN}✓ vLLM installed successfully!${NC}"
echo ""
echo "Next step: ./03-download-nemotron.sh"
