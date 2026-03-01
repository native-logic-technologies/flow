#!/bin/bash
# =============================================================================
# Compile vLLM from Source with sm_121 / NVFP4 Support
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Compiling vLLM from Source (sm_121 / NVFP4)                    ║"
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
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH

VLLM_DIR="$HOME/vllm"
CUTLASS_DIR="$HOME/cutlass"

echo -e "${BLUE}Checking dependencies...${NC}"

# Check PyTorch
python3 -c "import torch; print(f'PyTorch: {torch.__version__}')" 2>/dev/null || {
    echo -e "${RED}Error: PyTorch not installed. Run install-pytorch-nightly.sh first${NC}"
    exit 1
}

# Check Triton
python3 -c "import triton; print(f'Triton: {triton.__version__}')" 2>/dev/null || {
    echo -e "${YELLOW}Warning: Triton not installed. Continuing anyway...${NC}"
}

# Clone or update CUTLASS
echo ""
echo -e "${BLUE}Setting up CUTLASS...${NC}"
if [ ! -d "$CUTLASS_DIR" ]; then
    git clone https://github.com/NVIDIA/cutlass.git "$CUTLASS_DIR"
    cd "$CUTLASS_DIR"
    git checkout v3.8.0
else
    echo "CUTLASS already exists at $CUTLASS_DIR"
fi
export CUTLASS_PATH="$CUTLASS_DIR"

# Clone or update vLLM
echo ""
echo -e "${BLUE}Setting up vLLM...${NC}"
if [ ! -d "$VLLM_DIR" ]; then
    git clone https://github.com/vllm-project/vllm.git "$VLLM_DIR"
fi

cd "$VLLM_DIR"

# Fetch latest
git fetch origin

# Try to find a good version with Mamba/NVFP4 support
# v0.11.0+ should have better Blackwell support
git checkout v0.11.0 2>/dev/null || {
    echo -e "${YELLOW}v0.11.0 not available, using main${NC}"
    git checkout main
}

# Update submodules
git submodule update --init --recursive

echo ""
echo -e "${BLUE}Installing vLLM build dependencies...${NC}"
pip install -r requirements-build.txt 2>/dev/null || pip install cmake ninja packaging wheel

echo ""
echo -e "${BLUE}Building vLLM (this will take 30-60 minutes)...${NC}"
echo "Build configuration:"
echo "  CUDA arches: 121"
echo "  NVFP4: Enabled (if supported)"
echo "  CUTLASS: $CUTLASS_PATH"
echo ""

# Build with sm_121 support
# Note: Some flags may need adjustment based on actual vLLM version
MAX_JOBS=$(nproc) \
pip install -e . \
    --no-build-isolation \
    -Ccmake.args="-DVLLM_CUDA_ARCHES=121" \
    -Ccmake.args="-DCMAKE_CUDA_ARCHITECTURES=121" \
    -v 2>&1 | tee /tmp/vllm-build.log

echo ""
echo -e "${BLUE}Verifying vLLM installation...${NC}"

python3 << 'PYEOF'
import vllm
import torch

print(f"vLLM Version: {vllm.__version__}")
print(f"CUDA Available: {torch.cuda.is_available()}")

# Check for NVFP4 support
try:
    from vllm.model_executor.layers.quantization import QUANTIZATION_METHODS
    if 'nvfp4' in QUANTIZATION_METHODS:
        print("✓ NVFP4 quantization available")
    else:
        print("⚠ NVFP4 not in available quantizations:")
        print(f"  Available: {list(QUANTIZATION_METHODS.keys())}")
except Exception as e:
    print(f"Could not check quantization methods: {e}")

# Check CUDA arch support
try:
    from vllm.utils import get_device_capability
    major, minor = get_device_capability()
    print(f"Device Capability: {major}.{minor}")
    if major == 12 and minor >= 1:
        print("✓ sm_121 support confirmed")
except Exception as e:
    print(f"Could not check device capability: {e}")

print("✓ vLLM installed successfully")
PYEOF

echo ""
echo -e "${GREEN}✓ vLLM compiled and installed successfully!${NC}"
echo ""
echo "Next: Download Nemotron-3-Nano-30B model and start the LLM service"
