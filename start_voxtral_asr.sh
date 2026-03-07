#!/bin/bash
# Start Voxtral Mini 4B Realtime ASR on port 8001
# Optimized for DGX Spark (GB10) Blackwell

echo "🚀 Starting Voxtral Mini 4B Realtime ASR..."

# Environment for Blackwell
export VLLM_ATTENTION_BACKEND=FLASHINFER
export CUDA_VISIBLE_DEVICES=0
export HF_HOME=/tmp/hf_cache

# Memory settings for MPS isolation with Brain and Voice
export VOXTRAL_GPU_MEMORY_FRACTION=0.15

cd /home/phil/telephony-stack

# Start vLLM with Voxtral
exec /home/phil/telephony-stack-env/bin/python -m vllm.entrypoints.openai.api_server \
  --model /home/phil/telephony-stack/models/asr/voxtral-mini-4b-realtime \
  --tokenizer /home/phil/telephony-stack/models/asr/voxtral-mini-4b-realtime \
  --trust-remote-code \
  --gpu-memory-utilization $VOXTRAL_GPU_MEMORY_FRACTION \
  --max-model-len 4096 \
  --dtype bfloat16 \
  --enforce-eager \
  --port 8001 \
  --host 0.0.0.0
