#!/bin/bash
# =============================================================================
# Quick Fix: vLLM CUDA Library Compatibility
# Creates symlinks for libcudart.so.12 -> libcudart.so.13
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Quick Fix: vLLM CUDA Library Compatibility                     ║"
echo "║     (Create symlinks for libcudart.so.12)                          ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# This creates symlinks so that vLLM finds the CUDA 13 libraries
# when looking for CUDA 12 libraries

CUDA13_LIB="/usr/local/cuda-13.0/lib64"

echo -e "${YELLOW}Warning: This creates compatibility symlinks.${NC}"
echo -e "${YELLOW}For production, compile vLLM from source instead.${NC}"
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}This script requires sudo to create symlinks in system directories${NC}"
    echo "Run: sudo $0"
    exit 1
fi

echo -e "${BLUE}Creating symlinks...${NC}"

# Create symlinks for libcudart
cd "$CUDA13_LIB"

if [ ! -f "libcudart.so.12" ]; then
    ln -sf libcudart.so.13.0.96 libcudart.so.12
    echo "✓ Created: libcudart.so.12 -> libcudart.so.13.0.96"
fi

# Check for other CUDA 12 libraries that vLLM might need
for lib in libcublas.so.12 libcublasLt.so.12 libcufft.so.11 libcurand.so.10 libcusolver.so.11 libcusparse.so.12; do
    cuda12_name="$lib"
    # Find equivalent CUDA 13 library
    cuda13_equiv=$(ls lib${lib%.so.*}*.so.13* 2>/dev/null | head -1)
    
    if [ -n "$cuda13_equiv" ] && [ ! -f "$cuda12_name" ]; then
        ln -sf "$cuda13_equiv" "$cuda12_name"
        echo "✓ Created: $cuda12_name -> $cuda13_equiv"
    fi
done

echo ""
echo -e "${BLUE}Updating library cache...${NC}"
ldconfig

echo ""
echo -e "${GREEN}✓ Symlinks created${NC}"
echo ""
echo "Test with:"
echo "  source ~/telephony-stack-env/bin/activate"
echo "  python -c \"import vllm; print(vllm.__version__)\""
