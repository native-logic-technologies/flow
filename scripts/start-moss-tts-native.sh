#!/bin/bash
# =============================================================================
# Start MOSS-TTS-Realtime Native Server (Non-vLLM)
# Uses native PyTorch since vLLM doesn't support moss_tts_realtime architecture
# 
# CRITICAL: Includes PYTORCH_CUDA_ALLOC_CONF to prevent memory clashes with vLLM
# =============================================================================

set -e

source ~/telephony-stack-env/bin/activate

# CUDA 13.0 configuration
export CUDA_HOME=/usr/local/cuda-13.0

# CRITICAL: Prevents memory fragmentation and clashes with vLLM's pre-allocated blocks
# PyTorch uses expandable segments to dynamically grow without conflicting with vLLM
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# HuggingFace cache
export HF_HOME="${HF_HOME:-$HOME/telephony-stack/.cache/huggingface}"

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Starting MOSS-TTS-Realtime Native Server                          ║"
echo "║  Port: 8002                                                        ║"
echo "║  Mode: Native PyTorch (vLLM incompatible)                          ║"
echo "║  Feature: Real-time streaming (20ms chunks)                        ║"
echo "║  Memory: expandable_segments enabled (vLLM-safe)                   ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Environment:"
echo "  PYTORCH_CUDA_ALLOC_CONF=$PYTORCH_CUDA_ALLOC_CONF"
echo "  CUDA_HOME=$CUDA_HOME"
echo "  HF_HOME=$HF_HOME"
echo ""

# Run the FastAPI server
python ~/telephony-stack/tts/moss_tts_fastapi_server.py
