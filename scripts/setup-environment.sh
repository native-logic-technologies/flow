#!/bin/bash
# =============================================================================
# Environment Setup Script for DGX Spark Telephony Stack
# Run this once on a fresh DGX Spark
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  DGX Spark Telephony Stack - Environment Setup                     ║"
echo "║  Target: vLLM v0.16.0 + Nemotron + Voxtral                         ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check system
echo -e "${BLUE}Checking system...${NC}"

if ! command -v nvcc &> /dev/null; then
    echo -e "${RED}Error: CUDA not found${NC}"
    exit 1
fi

CUDA_VERSION=$(nvcc --version | grep "release" | awk '{print $5}' | cut -c2-)
echo "  CUDA Version: $CUDA_VERSION"

if [[ "$CUDA_VERSION" != 13.0* ]]; then
    echo -e "${YELLOW}Warning: Expected CUDA 13.0, found $CUDA_VERSION${NC}"
fi

# Install system dependencies
echo ""
echo -e "${BLUE}Installing system dependencies...${NC}"
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    cmake \
    ninja-build \
    git \
    git-lfs \
    python3-dev \
    python3.12-dev \
    libsndfile1 \
    libportaudio2 \
    redis-server \
    pkg-config

# Create directory structure
echo ""
echo -e "${BLUE}Creating directory structure...${NC}"
mkdir -p ~/telephony-stack/{models/{llm,asr,tts},scripts,.cache/huggingface}

# Add to .bashrc if not already present
echo ""
echo -e "${BLUE}Setting up environment variables...${NC}"

if ! grep -q "VLLM_WORKER_MULTIPROC_METHOD" ~/.bashrc; then
    cat >> ~/.bashrc << 'EOF'

# Telephony Stack Environment
export CUDA_HOME=/usr/local/cuda-13.0
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export TORCH_CUDA_ARCH_LIST="12.1"
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export HF_HOME=~/telephony-stack/.cache/huggingface
EOF
    echo -e "${GREEN}✓ Added environment variables to ~/.bashrc${NC}"
else
    echo -e "${YELLOW}Environment variables already configured${NC}"
fi

# Create Python virtual environment
echo ""
echo -e "${BLUE}Creating Python virtual environment...${NC}"
if [ ! -d "$HOME/telephony-stack-env" ]; then
    python3 -m venv ~/telephony-stack-env
    echo -e "${GREEN}✓ Created virtual environment${NC}"
else
    echo -e "${YELLOW}Virtual environment already exists${NC}"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo -e "║  ${GREEN}Environment setup complete!${NC}                                       ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Source the updated environment: source ~/.bashrc"
echo "  2. Activate virtual environment: source ~/telephony-stack-env/bin/activate"
echo "  3. Install PyTorch: ./scripts/install-pytorch.sh"
echo "  4. Build vLLM: ./scripts/build-vllm.sh"
echo "  5. Download models: ./scripts/download-models.sh"
echo ""
