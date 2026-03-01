#!/bin/bash
# =============================================================================
# Start MOSS-TTS-Realtime (TTS) with vLLM v0.16.0
# DGX Spark (GB10) - Blackwell SM121
# =============================================================================

set -e

# CRITICAL: Force Triton to use CUDA 13.0 compiler for JIT operations
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas

# Critical: Use spawn for ARM64/Blackwell
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export CUDA_HOME=/usr/local/cuda-13.0
export HF_HOME="${HF_HOME:-$HOME/telephony-stack/.cache/huggingface}"

# Model path
MODEL_PATH="${MODEL_PATH:-$HOME/telephony-stack/models/tts/moss-tts-realtime}"

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Starting MOSS-TTS-Realtime (TTS)                                  ║"
echo "║  Port: 8002                                                        ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Model: $MODEL_PATH"
echo "Architecture: MossTTSRealtime (Qwen3-based)"
echo "Dtype: bfloat16 (standard precision)"
echo "Size: 4.4 GB"
echo "GPU Memory: 15% (~12-15 GB expected)"
echo "Quantization: None (sensitive architecture)"
echo "Triton PTXAS: $TRITON_PTXAS_PATH"
echo ""
echo "Note: MOSS-TTS uses a novel architecture that requires standard"
echo "      FP16/BF16 precision. Do NOT use quantization."
echo ""

python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --dtype bfloat16 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.15 \
    --enforce-eager \
    --trust-remote-code \
    --port 8002
