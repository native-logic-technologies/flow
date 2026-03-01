#!/bin/bash
# =============================================================================
# Install PyTorch 2.9.0 Nightly with CUDA 13.0 / sm_121 support
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Installing PyTorch 2.9.0 Nightly (CUDA 13.0 / sm_121)          ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo -e "${YELLOW}Warning: Not in virtual environment${NC}"
    source "$HOME/telephony-stack-env/bin/activate" 2>/dev/null || {
        echo -e "${RED}Error: Cannot find virtual environment${NC}"
        exit 1
    }
fi

# Set build environment
export TORCH_CUDA_ARCH_LIST="12.1"
export CUDA_HOME=/usr/local/cuda-13.0
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH

echo -e "${BLUE}Environment:${NC}"
echo "  TORCH_CUDA_ARCH_LIST: $TORCH_CUDA_ARCH_LIST"
echo "  CUDA_HOME: $CUDA_HOME"
echo ""

# Check CUDA is available
if [ ! -d "$CUDA_HOME" ]; then
    echo -e "${RED}Error: CUDA_HOME not found at $CUDA_HOME${NC}"
    exit 1
fi

echo -e "${BLUE}Installing PyTorch 2.9.0 nightly...${NC}"
echo "This may take 30-60 minutes on first install..."
echo ""

# Install PyTorch nightly with CUDA 13.0
pip install --pre \
    torch \
    torchvision \
    torchaudio \
    --index-url https://download.pytorch.org/whl/nightly/cu130 \
    --upgrade \
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
    print(f"Device Capability: {torch.cuda.get_device_capability()}")
    
    # Check sm_121 support
    major, minor = torch.cuda.get_device_capability()
    if major == 12 and minor >= 1:
        print(f"✓ sm_121 support confirmed")
    else:
        print(f"⚠ Device capability is {major}.{minor}, expected 12.1+")
    
    # Quick GPU test
    x = torch.randn(1000, 1000).cuda()
    y = torch.matmul(x, x.t())
    print(f"✓ GPU computation test passed")
else:
    print("✗ CUDA not available!")
    sys.exit(1)
PYEOF

echo ""
echo -e "${GREEN}✓ PyTorch 2.9.0 nightly installed successfully!${NC}"
