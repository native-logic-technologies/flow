#!/bin/bash
# Deploy Qwen 3.5 9B (The Brain) on Port 8000
# Role: Logic, Tool Use, and WhatsApp KYC (Vision)
# Model: Qwen 3.5 9B NVFP4

echo "🧠 Starting Qwen 3.5 9B (The Brain) on Port 8000..."
echo ""

# Stop existing container if running
docker stop qwen-brain 2>/dev/null || true
docker rm qwen-brain 2>/dev/null || true
sleep 2

# Run vLLM with Qwen3.5-9B-NVFP4
docker run -d --name qwen-brain \
    --runtime nvidia --gpus all \
    --network host --ipc=host \
    -v /home/phil/telephony-stack/models:/models:ro \
    -e VLLM_ATTENTION_BACKEND=FLASHINFER \
    -e CUDA_DEVICE_ORDER=PCI_BUS_ID \
    vllm/vllm-openai@sha256:b6fcb1a19dad25e60e3e91e98ed36163978778fff2d82416c773ca033aa857eb \
    --model /models/quantized/Qwen3.5-9B-NVFP4 \
    --quantization modelopt_fp4 \
    --kv-cache-dtype fp8 \
    --gpu-memory-utilization 0.35 \
    --max-model-len 16384 \
    --trust-remote-code \
    --enforce-eager \
    --port 8000 \
    --api-key " cleans2s-brain-key"

echo "   Container started. Waiting for model to load..."
echo "   (This takes ~60-90 seconds for NVFP4 quantization)"
echo ""

# Wait for health check
for i in {1..120}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo ""
        echo "   ✅ Brain ready on port 8000"
        echo ""
        echo "   Model: Qwen3.5-9B-NVFP4"
        echo "   Quantization: NVFP4"
        echo "   Max context: 16384 tokens"
        echo ""
        break
    fi
    sleep 1
    if [ $i -eq 120 ]; then
        echo ""
        echo "   ❌ Brain failed to start"
        echo "   Check logs: docker logs -f qwen-brain"
        exit 1
    fi
    if [ $((i % 10)) -eq 0 ]; then
        echo -n "."
    fi
done

echo "🧠 Brain container running."
echo "   Logs: docker logs -f qwen-brain"
echo "   Test: curl http://localhost:8000/health"
