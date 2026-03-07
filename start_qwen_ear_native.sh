#!/bin/bash
# Deploy Qwen 2.5 Omni (The Ear) on Port 8001 - Native vLLM
# Role: Native Audio Ingress, Emotion Detection, Diarization
# Model: Qwen 2.5 Omni 7B FP8

echo "🎤 Starting Qwen 2.5 Omni (The Ear) on Port 8001..."
echo "   Using native vLLM (Docker lacks Qwen2.5-Omni support)"
echo ""

# Stop existing processes
pkill -f "vllm.*serve.*8001" 2>/dev/null || true
docker stop qwen-ear 2>/dev/null || true
docker rm qwen-ear 2>/dev/null || true
sleep 2

cd /home/phil/telephony-stack

# Set environment
export PYTHONPATH=/home/phil/telephony-stack:$PYTHONPATH
export HF_HOME=/tmp/hf_cache
export VLLM_ATTENTION_BACKEND=FLASHINFER
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas
export CUDA_DEVICE_ORDER=PCI_BUS_ID
# Force Triton to use system CUDA 13.0 ptxas (supports sm_121a)

# Start vLLM natively
/home/phil/telephony-stack-env/bin/python -m vllm.entrypoints.openai.api_server \
    --model /home/phil/telephony-stack/models/Qwen2.5-Omni-7B \
    --trust-remote-code \
    --dtype bfloat16 \
    --tensor-parallel-size 1 \
    --gpu-memory-utilization 0.40 \
    --max-model-len 8192 \
    --limit-mm-per-prompt '{"audio":1}' \
    --enforce-eager \
    --port 8001 \
    > /tmp/ear.log 2>&1 &

EAR_PID=$!
echo $EAR_PID > /tmp/ear.pid

echo "   vLLM starting (PID: $EAR_PID)..."
echo "   (Loading Qwen2.5-Omni, ~60-90 seconds)"
echo ""

# Wait for health check
for i in {1..120}; do
    if curl -s http://localhost:8001/health > /dev/null 2>&1; then
        echo ""
        echo "   ✅ Ear ready on port 8001"
        echo ""
        echo "   Model: Qwen2.5-Omni-7B"
        echo "   Dtype: bfloat16 (FP8 weights)"
        echo "   Capabilities: Audio + Vision + Text"
        echo "   Max context: 8192 tokens"
        echo "   GPU: 40% (~51GB)"
        echo ""
        break
    fi
    sleep 1
    if [ $i -eq 120 ]; then
        echo ""
        echo "   ❌ Ear failed to start"
        echo "   Check logs: tail -f /tmp/ear.log"
        exit 1
    fi
    if [ $((i % 10)) -eq 0 ]; then
        echo -n "."
    fi
done

echo "🎤 Ear running natively."
echo "   Logs: tail -f /tmp/ear.log"
echo "   Test: curl http://localhost:8001/health"
