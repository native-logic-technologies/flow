#!/bin/bash
# =============================================================================
# Start Voxtral-Mini-4B-Realtime-2602 (ASR) with vLLM v0.16.0
# DGX Spark (GB10) - Blackwell SM121
# =============================================================================

set -e

# CRITICAL: Force Triton to use CUDA 13.0 compiler for JIT operations
# The bundled Triton ptxas doesn't understand sm_121a (Blackwell)
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas

# Critical: Use spawn for ARM64/Blackwell
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export CUDA_HOME=/usr/local/cuda-13.0
export HF_HOME="${HF_HOME:-$HOME/telephony-stack/.cache/huggingface}"

# Model path
MODEL_PATH="${MODEL_PATH:-$HOME/telephony-stack/models/asr/voxtral-mini-4b-realtime}"

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Starting Voxtral-Mini-4B-Realtime-2602 (ASR)                      ║"
echo "║  Port: 8001                                                        ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Model: $MODEL_PATH"
echo "Dtype: bfloat16"
echo "GPU Memory: 10%"
echo "Max Context: 8192 tokens"
echo "Triton PTXAS: $TRITON_PTXAS_PATH"
echo ""

python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --dtype bfloat16 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.1 \
    --enforce-eager \
    --trust-remote-code \
    --port 8001
