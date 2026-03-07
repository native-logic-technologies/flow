#!/bin/bash
# Deploy Qwen 2.5 Omni (The Ear) on Port 8001
# Role: Native Audio Ingress, Emotion Detection, Diarization
# Model: Qwen 2.5 Omni 7B FP8

echo "🎤 Starting Qwen 2.5 Omni (The Ear) on Port 8001..."
echo ""

# Stop existing container if running
docker stop qwen-ear 2>/dev/null || true
docker rm qwen-ear 2>/dev/null || true
sleep 2

# Run vLLM with Qwen2.5-Omni-7B
docker run -d --name qwen-ear \
    --runtime nvidia --gpus all \
    --network host --ipc=host \
    -v /home/phil/telephony-stack/models:/models:ro \
    -e VLLM_ATTENTION_BACKEND=FLASHINFER \
    -e CUDA_DEVICE_ORDER=PCI_BUS_ID \
    vllm/vllm-openai@sha256:b6fcb1a19dad25e60e3e91e98ed36163978778fff2d82416c773ca033aa857eb \
    --model /models/Qwen2.5-Omni-7B \
    --trust-remote-code \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.40 \
    --max-model-len 8192 \
    --limit-mm-per-prompt "audio=1,image=1" \
    --enforce-eager \
    --port 8001 \
    --api-key " cleans2s-ear-key"

echo "   Container started. Waiting for model to load..."
echo "   (This takes ~60 seconds for FP8 weights)"
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
        echo ""
        break
    fi
    sleep 1
    if [ $i -eq 120 ]; then
        echo ""
        echo "   ❌ Ear failed to start"
        echo "   Check logs: docker logs -f qwen-ear"
        exit 1
    fi
    if [ $((i % 10)) -eq 0 ]; then
        echo -n "."
    fi
done

echo "🎤 Ear container running."
echo "   Logs: docker logs -f qwen-ear"
echo "   Test: curl http://localhost:8001/health"
