#!/bin/bash
# Deploy Qwen2-Audio-7B-Instruct as ASR replacement
# Port: 8001 (replacing Voxtral)

set -e

echo "=== Deploying Qwen2-Audio-7B-Instruct ==="

# Stop any existing container on port 8001
docker stop qwen2-audio-asr 2>/dev/null || true
docker rm qwen2-audio-asr 2>/dev/null || true

# Pull latest vLLM image for Blackwell
docker pull vllm/vllm-openai:cu130-nightly

echo ""
echo "=== Starting Qwen2-Audio-7B ==="
docker run -d \
  --name qwen2-audio-asr \
  --runtime nvidia \
  --gpus all \
  -p 8001:8000 \
  --ipc=host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -e HF_TOKEN=${HF_TOKEN} \
  -e VLLM_GPU_MEMORY_UTILIZATION=0.85 \
  -e VLLM_MAX_NUM_SEQS=256 \
  -e VLLM_WORKER_MULTIPROC_METHOD=spawn \
  vllm/vllm-openai:cu130-nightly \
  --model Qwen/Qwen2-Audio-7B-Instruct \
  --dtype float16 \
  --max-model-len 8192 \
  --tensor-parallel-size 1 \
  --enable-prefix-caching \
  --limit-mm-per-prompt audio=5

echo ""
echo "=== Waiting for model to load (this may take 2-3 minutes)... ==="
sleep 10

# Health check
for i in {1..30}; do
  if curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo "✓ Qwen2-Audio is ready!"
    break
  fi
  echo -n "."
  sleep 5
done

echo ""
echo "=== Verifying deployment ==="
curl -s http://localhost:8001/v1/models | head -100

echo ""
echo "=== GPU Status ==="
nvidia-smi | grep -E "MiB|Qwen2"

echo ""
echo "=== Qwen2-Audio-7B deployed on port 8001 ==="
echo "API endpoint: http://localhost:8001/v1/chat/completions"
