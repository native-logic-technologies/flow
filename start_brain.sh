#!/bin/bash
# Start Nemotron Brain with proper environment
export CUDA_VISIBLE_DEVICES=0
export VLLM_ATTENTION_BACKEND=FLASHINFER
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas
export PATH=/usr/local/cuda-13.0/bin:$PATH
export HF_HOME=/tmp/hf_cache

exec /home/phil/telephony-stack-env/bin/python -m vllm.entrypoints.openai.api_server \
  --model /home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4 \
  --quantization modelopt_fp4 \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization 0.18 \
  --max-model-len 4096 \
  --enforce-eager \
  --port 8000 \
  --trust-remote-code \
  "$@"
