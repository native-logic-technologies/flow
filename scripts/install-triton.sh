#!/bin/bash
# =============================================================================
# Compile Triton from Source for sm_121
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Compiling Triton from Source (sm_121)                          ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    source "$HOME/telephony-stack-env/bin/activate" 2>/dev/null || {
        echo -e "${RED}Error: Not in virtual environment${NC}"
        exit 1
    }
fi

export TORCH_CUDA_ARCH_LIST="12.1"
export CUDA_HOME=/usr/local/cuda-13.0

TRITON_DIR="$HOME/triton"

echo -e "${BLUE}Checking for existing Triton installation...${NC}"

if [ -d "$TRITON_DIR" ]; then
    echo -e "${YELLOW}Triton directory exists at $TRITON_DIR${NC}"
    read -p "Remove and reclone? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$TRITON_DIR"
    else
        echo "Using existing Triton directory"
    fi
fi

if [ ! -d "$TRITON_DIR" ]; then
    echo -e "${BLUE}Cloning Triton repository...${NC}"
    git clone https://github.com/triton-lang/triton.git "$TRITON_DIR"
fi

cd "$TRITON_DIR"

echo -e "${BLUE}Checking out compatible branch...${NC}"
# Try to find a compatible branch/tag for PyTorch 2.9.0
git fetch origin
git checkout release/3.3.x 2>/dev/null || git checkout main

# Update submodules
git submodule update --init --recursive

cd python

echo -e "${BLUE}Installing Triton build dependencies...${NC}"
pip install cmake ninja

echo -e "${BLUE}Building Triton (this may take 20-40 minutes)...${NC}"
pip install -e . --no-build-isolation -v 2>&1 | tee /tmp/triton-build.log

echo ""
echo -e "${BLUE}Verifying Triton installation...${NC}"

python3 << 'PYEOF'
try:
    import triton
    print(f"Triton Version: {triton.__version__}")
    
    # Quick functionality test
    import torch
    import triton.language as tl
    from triton import jit
    
    @jit
def kernel(x_ptr, y_ptr, n_elements, BLOCK_SIZE: tl.constexpr):
        pid = tl.program_id(axis=0)
        block_start = pid * BLOCK_SIZE
        offsets = block_start + tl.arange(0, BLOCK_SIZE)
        mask = offsets < n_elements
        x = tl.load(x_ptr + offsets, mask=mask)
        tl.store(y_ptr + offsets, x * 2, mask=mask)
    
    # Test on GPU
    x = torch.randn(1024, device='cuda')
    y = torch.empty_like(x)
    kernel[(4,)](x, y, x.numel(), BLOCK_SIZE=256)
    
    print("✓ Triton kernel test passed")
    
except Exception as e:
    print(f"✗ Triton test failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
PYEOF

echo ""
echo -e "${GREEN}✓ Triton compiled and installed successfully!${NC}"
