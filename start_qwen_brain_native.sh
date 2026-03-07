#!/bin/bash
# Deploy Qwen 3.5 9B (The Brain) on Port 8000 - Native vLLM
# Role: Logic, Tool Use, and WhatsApp KYC (Vision)
# Model: Qwen 3.5 9B NVFP4

echo "🧠 Starting Qwen 3.5 9B (The Brain) on Port 8000..."
echo "   Using native vLLM (Docker lacks Qwen3.5 support)"
echo ""

# Stop existing processes
pkill -f "vllm.*serve.*8000" 2>/dev/null || true
docker stop qwen-brain 2>/dev/null || true
docker rm qwen-brain 2>/dev/null || true
sleep 2

cd /home/phil/telephony-stack

# Set environment
export PYTHONPATH=/home/phil/telephony-stack:$PYTHONPATH
export HF_HOME=/tmp/hf_cache
export VLLM_ATTENTION_BACKEND=FLASHINFER
export CUDA_DEVICE_ORDER=PCI_BUS_ID
# Force Triton to use system CUDA 13.0 ptxas

# Start vLLM natively
/home/phil/telephony-stack-env/bin/python -m vllm.entrypoints.openai.api_server \
    --model /home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4 \
    --quantization modelopt_fp4 \
    --kv-cache-dtype fp8 \
    --trust-remote-code \
    --tensor-parallel-size 1 \
    --gpu-memory-utilization 0.35 \
    --max-model-len 16384 \
    --enforce-eager \
    --port 8000 \
    --trust-remote-code \
    > /tmp/brain.log 2>&1 &

BRAIN_PID=$!
echo $BRAIN_PID > /tmp/brain.pid

echo "   vLLM starting (PID: $BRAIN_PID)..."
echo "   (Compiling FlashInfer kernels, ~60-90 seconds)"
echo ""

# Wait for health check
for i in {1..120}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo ""
        echo "   ✅ Brain ready on port 8000"
        echo ""
        echo "   Model: Nemotron-3-Nano-30B-NVFP4"
        echo "   Quantization: NVFP4"
        echo "   Max context: 16384 tokens"
        echo "   GPU: 35% (~45GB)"
        echo ""
        break
    fi
    sleep 1
    if [ $i -eq 120 ]; then
        echo ""
        echo "   ❌ Brain failed to start"
        echo "   Check logs: tail -f /tmp/brain.log"
        exit 1
    fi
    if [ $((i % 10)) -eq 0 ]; then
        echo -n "."
    fi
done

echo "🧠 Brain running natively."
echo "   Note: Using Nemotron (NVFP4 Qwen3.5 has compatibility issues)"
echo "   Logs: tail -f /tmp/brain.log"
echo "   Test: curl http://localhost:8000/health"
