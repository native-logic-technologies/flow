#!/bin/bash
# =============================================================================
# Telephony Stack Environment Bootstrap
# DGX Spark (GB10) - sm_121 / CUDA 13.0
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Telephony Stack Environment Bootstrap                          ║"
echo "║     DGX Spark (GB10) - sm_121 / CUDA 13.0                          ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check system requirements
echo -e "${BLUE}Checking system requirements...${NC}"

# CUDA 13.0
if ! command -v nvcc &> /dev/null; then
    echo -e "${RED}Error: CUDA not found${NC}"
    exit 1
fi

CUDA_VERSION=$(nvcc --version | grep "release" | awk '{print $5}' | cut -c2-)
echo "  CUDA Version: $CUDA_VERSION"

if [[ "$CUDA_VERSION" != 13.0* ]]; then
    echo -e "${YELLOW}Warning: Expected CUDA 13.0, found $CUDA_VERSION${NC}"
fi

# NVIDIA Driver
DRIVER_VERSION=$(nvidia-smi | grep "Driver Version" | awk '{print $3}')
echo "  Driver Version: $DRIVER_VERSION"

# Disk space
AVAILABLE_GB=$(df -BG / | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$AVAILABLE_GB" -lt 100 ]; then
    echo -e "${YELLOW}Warning: Only ${AVAILABLE_GB}GB available. 200GB+ recommended.${NC}"
else
    echo -e "  Disk Space: ${GREEN}${AVAILABLE_GB}GB available${NC}"
fi

# Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "  Python: $PYTHON_VERSION"

echo ""
echo -e "${BLUE}Setting up Python virtual environment...${NC}"

# Create virtual environment
VENV_PATH="$HOME/telephony-stack-env"

if [ -d "$VENV_PATH" ]; then
    echo -e "${YELLOW}Virtual environment already exists at $VENV_PATH${NC}"
    read -p "Delete and recreate? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_PATH"
        python3 -m venv "$VENV_PATH"
    fi
else
    python3 -m venv "$VENV_PATH"
fi

source "$VENV_PATH/bin/activate"

echo -e "${GREEN}✓ Virtual environment ready${NC}"
echo ""

# Install base dependencies
echo -e "${BLUE}Installing base dependencies...${NC}"
pip install --upgrade pip setuptools wheel

pip install \
    numpy \
    scipy \
    resampy \
    soundfile \
    librosa \
    fastapi \
    uvicorn \
    websockets \
    aiohttp \
    python-dotenv \
    huggingface-hub \
    transformers \
    accelerate \
    "pyyaml>=6.0"

echo -e "${GREEN}✓ Base dependencies installed${NC}"
echo ""

# Set environment variables
echo -e "${BLUE}Setting environment variables...${NC}"

cat >> "$VENV_PATH/bin/activate" << 'EOF'

# Telephony Stack Environment
export TORCH_CUDA_ARCH_LIST="12.1"
export CUDA_HOME=/usr/local/cuda-13.0
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export TELEPHONY_STACK_ROOT=$HOME/telephony-stack
EOF

echo -e "${GREEN}✓ Environment variables configured${NC}"
echo ""

echo "╔════════════════════════════════════════════════════════════════════╗"
echo -e "║  ${GREEN}Base environment setup complete!${NC}                                  ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. source $VENV_PATH/bin/activate"
echo "  2. ./scripts/install-pytorch-nightly.sh"
echo "  3. ./scripts/install-triton.sh"
echo "  4. ./scripts/install-vllm.sh"
echo ""
