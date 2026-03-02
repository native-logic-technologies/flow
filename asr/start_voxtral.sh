#!/bin/bash
# Start Voxtral-Mini-4B-Realtime-2602 ASR Server
# Optimized for DGX Spark (GB10) Blackwell

set -e

cd "$(dirname "$0")"

# Check if we're in the right environment
if ! python3 -c "import torch; print(torch.__version__)" 2>/dev/null | grep -q "2."; then
    echo "ERROR: Python environment not activated. Please activate telephony-stack-env"
    echo "  source ~/telephony-stack-env/bin/activate"
    exit 1
fi

# Check CUDA
if ! python3 -c "import torch; assert torch.cuda.is_available(), 'CUDA not available'" 2>/dev/null; then
    echo "ERROR: CUDA not available in Python"
    exit 1
fi

echo "=================================="
echo "Voxtral-Mini-4B-Realtime-2602 ASR"
echo "=================================="
echo "Device: $(python3 -c 'import torch; print(torch.cuda.get_device_name(0))')"
echo "CUDA: $(python3 -c 'import torch; print(torch.version.cuda)')"
echo "PyTorch: $(python3 -c 'import torch; print(torch.__version__)')"
echo "Port: 8001"
echo "=================================="
echo ""

# Check if model directory exists and has enough space
if [ ! -d "/mnt/models" ]; then
    echo "WARNING: /mnt/models directory not found. Using default cache."
    echo "Consider creating /mnt/models for faster NVMe storage."
fi

# Set HuggingFace cache to avoid permission issues
export HF_HOME="$HOME/telephony-stack/models/hf_cache"
export TRANSFORMERS_CACHE="$HOME/telephony-stack/models/hf_cache"
mkdir -p "$HF_HOME"

# Set environment for optimal Blackwell performance
export PYTORCH_ALLOC_CONF="expandable_segments:True,max_split_size_mb:512"
export CUDA_VISIBLE_DEVICES=0

# Run the server
exec python3 voxtral_server.py "$@"
