#!/bin/bash
# Start Voxtral-Mini-4B-Realtime-2602 using vLLM with native architecture support
# Optimized for DGX Spark (GB10) Blackwell SM121

set -e

cd "$(dirname "$0")"

# Check if we're in the right environment
if ! python3 -c "import vllm; print(vllm.__version__)" 2>/dev/null | grep -q "0.16"; then
    echo "ERROR: vLLM 0.16+ not found. Please activate telephony-stack-env"
    echo "  source ~/telephony-stack-env/bin/activate"
    exit 1
fi

echo "=================================="
echo "Voxtral-Mini-4B-Realtime-2602 ASR"
echo "Using vLLM Native Architecture"
echo "=================================="
echo "Model: mistralai/Voxtral-Mini-4B-Realtime-2602"
echo "Architecture: VoxtralForConditionalGeneration"
echo "Port: 8001"
echo "Dtype: bfloat16 (Blackwell Tensor Cores)"
echo "=================================="
echo ""

# Set environment for Blackwell compilation
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas
export CUDA_HOME=/usr/local/cuda-13.0
export PATH=$CUDA_HOME/bin:$PATH

# HuggingFace cache
export HF_HOME="$HOME/telephony-stack/models/hf_cache"
mkdir -p "$HF_HOME"

# Kill any existing process on port 8001
pkill -f "voxtral" 2>/dev/null || true
pkill -f "port 8001" 2>/dev/null || true
sleep 1

echo "Starting vLLM with Voxtral architecture..."
echo ""

# Run vLLM with Voxtral-specific architecture flag
# This uses the native interleaved audio-text kernels
exec python3 -m vllm.entrypoints.openai.api_server \
    --model mistralai/Voxtral-Mini-4B-Realtime-2602 \
    --trust-remote-code \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.15 \
    --max-model-len 8192 \
    --max-num-seqs 4 \
    --port 8001 \
    --uvloop-disabled \
    --enable-realtime-api
