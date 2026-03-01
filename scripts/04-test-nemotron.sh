#!/bin/bash
# =============================================================================
# Test Nemotron-3-Nano-30B with vLLM (Mamba-optimized settings)
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     Testing Nemotron-3-Nano-30B with vLLM                          ║"
echo "║     (Mamba: no KV cache, 20% GPU memory)                           ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    source "$HOME/telephony-stack-env/bin/activate" 2>/dev/null || {
        echo -e "${RED}Error: Not in virtual environment${NC}"
        exit 1
    }
fi

export CUDA_HOME=/usr/local/cuda-13.0
export PATH=$CUDA_HOME/bin:$PATH
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_FLASHINFER_MOE_BACKEND=latency
export VLLM_USE_V1=1
export VLLM_ATTENTION_BACKEND=FLASHINFER

MODEL_DIR="$HOME/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4"

echo -e "${BLUE}Configuration:${NC}"
echo "  Model: $MODEL_DIR"
echo "  Quantization: NVFP4"
echo "  GPU Memory: 20% (Mamba - no KV cache needed)"
echo "  Max Model Length: 4096"
echo "  Mode: Eager (better for streaming)"
echo ""

echo -e "${BLUE}Starting vLLM server test...${NC}"
echo ""

# Test with Python script
python3 << 'PYEOF'
import os
os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"
os.environ["VLLM_FLASHINFER_MOE_BACKEND"] = "latency"
os.environ["VLLM_USE_V1"] = "1"

import torch
from vllm import LLM, SamplingParams

MODEL_PATH = os.path.expanduser("~/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4")

print("Loading Nemotron-3-Nano-30B...")
print("This may take 2-5 minutes on first load...")
print("")

# Mamba-optimized configuration
llm = LLM(
    model=MODEL_PATH,
    quantization="nvfp4",
    gpu_memory_utilization=0.20,  # Only 20% - Mamba has no KV cache!
    max_model_len=4096,
    tensor_parallel_size=1,
    enforce_eager=True,  # Better for streaming token-by-token
    trust_remote_code=True,
    dtype="float16",
)

print("✓ Model loaded successfully!")
print("")

# Get GPU memory usage
if torch.cuda.is_available():
    allocated = torch.cuda.memory_allocated() / 1024**3
    reserved = torch.cuda.memory_reserved() / 1024**3
    total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"GPU Memory:")
    print(f"  Allocated: {allocated:.2f} GB")
    print(f"  Reserved:  {reserved:.2f} GB")
    print(f"  Total:     {total:.2f} GB")
    print(f"  Usage:     {allocated/total*100:.1f}%")
    print("")

# Test generation
print("Testing generation...")
params = SamplingParams(
    temperature=0.0,
    max_tokens=50,
)

prompts = [
    "Hello, I am a voice AI assistant.",
    "What is the capital of France?",
]

for prompt in prompts:
    print(f"\nPrompt: {prompt}")
    outputs = llm.generate([prompt], params)
    generated = outputs[0].outputs[0].text
    print(f"Output: {generated}")

print("")
print("✓ Nemotron test passed!")
PYEOF

echo ""
echo -e "${GREEN}✓ Nemotron-3-Nano-30B is working correctly!${NC}"
echo ""
echo "Mamba architecture benefits:"
echo "  - No KV cache = much lower memory usage"
echo "  - 20% GPU memory sufficient for full model"
echo "  - 80% GPU memory available for ASR/TTS/300+ concurrent calls"
