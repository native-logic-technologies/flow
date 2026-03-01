#!/bin/bash
# =============================================================================
# Install PyTorch 2.9.1 with CUDA 13.0
# =============================================================================

set -e

source ~/telephony-stack-env/bin/activate

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Installing PyTorch 2.9.1 (CUDA 13.0)                              ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

export CUDA_HOME=/usr/local/cuda-13.0

pip install --upgrade pip setuptools wheel

pip install torch==2.9.1+cu130 torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu130 \
    --no-cache-dir

echo ""
echo "Verifying installation..."
python << 'PYEOF'
import torch
print(f"PyTorch: {torch.__version__}")
print(f"CUDA: {torch.version.cuda}")
print(f"Available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"Device: {torch.cuda.get_device_name(0)}")
    print(f"Capability: {torch.cuda.get_device_capability()}")
    # Quick test
    x = torch.randn(100, 100, device='cuda')
    y = torch.matmul(x, x.t())
    torch.cuda.synchronize()
    print("✓ GPU test passed")
PYEOF

echo ""
echo "Installing build dependencies..."
pip install ninja packaging setuptools-scm cmake build

echo ""
echo "✅ PyTorch installation complete!"
