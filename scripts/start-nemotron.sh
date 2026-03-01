#!/bin/bash
# =============================================================================
# Start Nemotron-3-Nano-30B-A3B-NVFP4 (LLM) with vLLM v0.16.0
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
MODEL_PATH="${MODEL_PATH:-$HOME/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4}"

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Starting Nemotron-3-Nano-30B-A3B-NVFP4 (LLM)                      ║"
echo "║  Port: 8000                                                        ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Model: $MODEL_PATH"
echo "Quantization: modelopt_fp4 (NVFP4)"
echo "GPU Memory: 20% (Mamba - no KV cache)"
echo "Max Context: 32768 tokens"
echo "Triton PTXAS: $TRITON_PTXAS_PATH"
echo ""

python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --quantization modelopt_fp4 \
    --gpu-memory-utilization 0.2 \
    --max-model-len 32768 \
    --enforce-eager \
    --trust-remote-code \
    --port 8000 \
    --no-enable-reasoning
