#!/bin/bash
# =============================================================================
# Build vLLM v0.16.0 from source for DGX Spark (SM121)
# This is REQUIRED - pre-built wheels don't support CUDA 13.0 / Blackwell
# =============================================================================

set -e

source ~/telephony-stack-env/bin/activate

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Building vLLM v0.16.0 from Source                                 ║"
echo "║  Target: CUDA 13.0 / SM121 (Blackwell)                             ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "⚠️  This will take 30-60 minutes. Do not interrupt."
echo ""

# Set build environment
export TORCH_CUDA_ARCH_LIST="12.1"
export VLLM_INSTALL_PUNICA_KERNELS=1
export CUDA_HOME=/usr/local/cuda-13.0

# Clone if not exists
if [ ! -d "$HOME/vllm-src" ]; then
    echo "Cloning vLLM repository..."
    git clone https://github.com/vllm-project/vllm.git ~/vllm-src
fi

cd ~/vllm-src

echo "Checking out v0.16.0..."
git fetch origin
git checkout v0.16.0

# Clean previous builds
rm -rf build dist *.egg-info .eggs

echo ""
echo "Starting build..."
pip install -e . --no-build-isolation

echo ""
echo "Verifying build..."
python << 'PYEOF'
import os
os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"

import vllm
print(f"vLLM Version: {vllm.__version__}")

from vllm import LLM, SamplingParams
print("✓ vLLM imports successful")
PYEOF

echo ""
echo "✅ vLLM v0.16.0 built successfully!"
echo ""
echo "Features enabled:"
echo "  - SM121 (Blackwell) support"
echo "  - NVFP4 Tensor Cores"
echo "  - MoE kernels"
echo "  - Mamba SSM"
echo "  - FLASHINFER attention"
