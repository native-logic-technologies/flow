#!/bin/bash
# =============================================================================
# Install PyTorch 2.9.0 with CUDA 13.0 (cu130) - Pre-built Wheels
# Based on: https://github.com/anveshkumar0206/vllm-on-DGX-Spark
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Installing PyTorch 2.9.0 (CUDA 13.0 cu130)                     ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source "$HOME/telephony-stack-env/bin/activate" 2>/dev/null || {
        echo -e "${RED}Error: Virtual environment not found at ~/telephony-stack-env${NC}"
        echo "Run ./bootstrap-environment.sh first"
        exit 1
    }
fi

# Verify CUDA 13.0
if [ ! -d "/usr/local/cuda-13.0" ]; then
    echo -e "${RED}Error: CUDA 13.0 not found at /usr/local/cuda-13.0${NC}"
    exit 1
fi

export CUDA_HOME=/usr/local/cuda-13.0
export PATH=$CUDA_HOME/bin:$PATH

echo -e "${BLUE}Installing PyTorch 2.9.0 with cu130 support...${NC}"
echo "This uses pre-built wheels (much faster than compiling)"
echo ""

# Install from cu130 index
pip install --upgrade pip

pip install \
    torch==2.9.0 \
    torchvision==0.24.0 \
    torchaudio==2.9.0 \
    --extra-index-url https://download.pytorch.org/whl/cu130 \
    --no-cache-dir

echo ""
echo -e "${BLUE}Verifying PyTorch installation...${NC}"

python3 << 'PYEOF'
import torch
import sys

print(f"PyTorch Version: {torch.__version__}")
print(f"CUDA Available: {torch.cuda.is_available()}")
print(f"CUDA Version: {torch.version.cuda}")

if torch.cuda.is_available():
    print(f"Device: {torch.cuda.get_device_name(0)}")
    cap = torch.cuda.get_device_capability()
    print(f"Device Capability: {cap}")
    
    if cap[0] >= 12:
        print(f"✓ Blackwell architecture detected")
    
    # Test GPU
    x = torch.randn(1000, 1000, device='cuda')
    y = torch.matmul(x, x.t())
    torch.cuda.synchronize()
    print(f"✓ GPU computation test passed")
else:
    print("✗ CUDA not available!")
    sys.exit(1)
PYEOF

echo ""
echo -e "${GREEN}✓ PyTorch 2.9.0 installed successfully!${NC}"
echo ""
echo "Next step: ./02-install-vllm.sh"
