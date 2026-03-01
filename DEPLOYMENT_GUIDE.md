# DGX Spark (GB10) Telephony Stack Deployment Guide

Complete deployment guide for high-concurrency 8kHz voice AI stack on NVIDIA DGX Spark (GB10) with Blackwell SM121 architecture.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [System Preparation](#system-preparation)
3. [Base Environment Setup](#base-environment-setup)
4. [vLLM v0.16.0 Compilation](#vllm-v0160-compilation)
5. [Model Downloads](#model-downloads)
6. [Service Deployment](#service-deployment)
7. [Verification](#verification)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Hardware Requirements

- **NVIDIA DGX Spark (GB10)**
  - ARM64 (aarch64) architecture
  - Blackwell GPU (SM121 / CUDA capability 12.1)
  - 128GB unified memory
  - CUDA 13.0 installed

### Software Requirements

- Ubuntu 24.04 (DGX OS)
- NVIDIA Driver 570+ (should have CUDA 13.0 support)
- Python 3.12
- Git, build tools
- 200GB+ free disk space
- HuggingFace token with model access

### Verify System

```bash
# Check CUDA version
nvcc --version
# Expected: Cuda compilation tools, release 13.0

# Check GPU
nvidia-smi
# Expected: NVIDIA GB10, CUDA Version: 13.0

# Check architecture
uname -m
# Expected: aarch64
```

---

## System Preparation

### 1. Install System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    cmake \
    ninja-build \
    git \
    git-lfs \
    python3-dev \
    python3.12-dev \
    libsndfile1 \
    libportaudio2 \
    redis-server \
    pkg-config
```

### 2. Create Directory Structure

```bash
mkdir -p ~/telephony-stack/{models/{llm,asr,tts},scripts,.cache/huggingface}
cd ~/telephony-stack
```

### 3. Set Environment Variables (Add to ~/.bashrc)

```bash
# Core environment
export CUDA_HOME=/usr/local/cuda-13.0
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export TORCH_CUDA_ARCH_LIST="12.1"

# vLLM critical settings
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export HF_HOME=~/telephony-stack/.cache/huggingface

# CRITICAL: Triton JIT compiler fix for Blackwell (sm_121a)
# The bundled Triton ptxas doesn't understand Blackwell architecture
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas

# HuggingFace token (replace with yours)
export HF_TOKEN=your_token_here
```

Apply changes:
```bash
source ~/.bashrc
```

---

## Base Environment Setup

### 1. Create Python Virtual Environment

```bash
cd ~
python3 -m venv telephony-stack-env
source telephony-stack-env/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel
```

### 2. Install PyTorch with CUDA 13.0

```bash
# Install PyTorch 2.9.1 with CUDA 13.0 support
pip install torch==2.9.1+cu130 torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu130 \
    --no-cache-dir

# Verify installation
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA: {torch.version.cuda}'); print(f'Available: {torch.cuda.is_available()}')"
```

Expected output:
```
PyTorch: 2.9.1+cu130
CUDA: 13.0
Available: True
```

### 3. Install Build Dependencies

```bash
pip install ninja packaging setuptools-scm cmake build
```

---

## vLLM v0.16.0 Compilation

This is the **most critical step**. vLLM must be compiled from source for CUDA 13.0 / SM121 support.

### 1. Clone vLLM Repository

```bash
cd ~
git clone https://github.com/vllm-project/vllm.git vllm-src
cd vllm-src
git checkout v0.16.0
```

### 2. Build from Source

```bash
# Set build environment
export TORCH_CUDA_ARCH_LIST="12.1"
export VLLM_INSTALL_PUNICA_KERNELS=1
export CUDA_HOME=/usr/local/cuda-13.0

# Clean any previous builds
rm -rf build dist *.egg-info .eggs

# Build vLLM (takes 30-60 minutes)
pip install -e . --no-build-isolation
```

**What happens during build:**
- Compiles CUDA kernels for SM121 (Blackwell)
- Builds NVFP4 Tensor Core support
- Builds MoE (Mixture of Experts) kernels
- Compiles Mamba SSM kernels
- Builds FLASHINFER attention backend

### 3. Verify Build

```bash
python -c "import vllm; print(f'vLLM: {vllm.__version__}')"
```

Expected output:
```
vLLM: 0.16.0+cu130
```

**⚠️ Common Build Issues:**

**Issue:** `ModuleNotFoundError: No module named 'setuptools_scm'`
**Fix:** `pip install setuptools-scm`

**Issue:** `CMake Error: Could NOT find Python`
**Fix:** `sudo apt-get install python3-dev python3.12-dev`

**Issue:** `CMake Error: Ninja not found`
**Fix:** `sudo apt-get install ninja-build`

---

## Model Downloads

### 1. Nemotron-3-Nano-30B-A3B-NVFP4 (LLM)

```bash
# Download to local directory (avoids cache permission issues)
huggingface-cli download \
    nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
    --local-dir ~/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4 \
    --local-dir-use-symlinks False \
    --token $HF_TOKEN
```

**Specs:**
- Size: ~19 GB
- Architecture: Mamba-Hybrid (NemotronHForCausalLM)
- Quantization: NVFP4 (modelopt_fp4)
- Max context: 32768 tokens

### 2. Voxtral-Mini-4B-Realtime-2602 (ASR)

```bash
huggingface-cli download \
    mistralai/Voxtral-Mini-4B-Realtime-2602 \
    --local-dir ~/telephony-stack/models/asr/voxtral-mini-4b-realtime \
    --local-dir-use-symlinks False
```

**Specs:**
- Size: ~17 GB
- Architecture: VoxtralRealtimeForConditionalGeneration
- Realtime API: Auto-enabled based on model config
- Max context: 8192 tokens

### 3. MOSS-TTS-Realtime (TTS)

```bash
huggingface-cli download \
    OpenMOSS-Team/MOSS-TTS-Realtime \
    --local-dir ~/telephony-stack/models/tts/moss-tts-realtime \
    --local-dir-use-symlinks False \
    --token $HF_TOKEN
```

**Specs:**
- Size: ~4.4 GB
- Architecture: MossTTSRealtime (Qwen3-based backbone)
- **CRITICAL**: Uses standard FP16/BF16 (NO quantization)
- Custom audio token generation
- Max context: 4096 tokens

**⚠️ Important**: MOSS-TTS uses a novel architecture sensitive to quantization. Must use `--dtype bfloat16` without any `--quantization` flag.

### 4. Verify Downloads

```bash
# Check Nemotron
ls -lh ~/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4/*.safetensors

# Check Voxtral
ls -lh ~/telephony-stack/models/asr/voxtral-mini-4b-realtime/*.safetensors
```

---

## Service Deployment

### Terminal 1: Nemotron LLM (Port 8000)

```bash
source ~/telephony-stack-env/bin/activate
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export HF_HOME=~/telephony-stack/.cache/huggingface

# CRITICAL: Force Triton to use CUDA 13.0 compiler (Blackwell/sm_121a support)
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas

python -m vllm.entrypoints.openai.api_server \
    --model ~/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4 \
    --quantization modelopt_fp4 \
    --gpu-memory-utilization 0.2 \
    --max-model-len 32768 \
    --enforce-eager \
    --trust-remote-code \
    --port 8000
```

**Key flags explained:**
- `--quantization modelopt_fp4`: Required! Model uses ModelOpt FP4 format
- `--enforce-eager`: Required for Mamba architecture (prevents CUDA graph overhead)
- `--trust-remote-code`: Required for custom Nemotron model code
- `--gpu-memory-utilization 0.2`: Only 20% of GPU (Mamba has no KV cache!)

### Terminal 2: Voxtral ASR (Port 8001)

```bash
source ~/telephony-stack-env/bin/activate
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export HF_HOME=~/telephony-stack/.cache/huggingface

# CRITICAL: Force Triton to use CUDA 13.0 compiler (Blackwell/sm_121a support)
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas

python -m vllm.entrypoints.openai.api_server \
    --model ~/telephony-stack/models/asr/voxtral-mini-4b-realtime \
    --dtype bfloat16 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.1 \
    --enforce-eager \
    --trust-remote-code \
    --port 8001
```

### Terminal 3: MOSS-TTS (Port 8002) - Native PyTorch

**⚠️ CRITICAL**: MOSS-TTS-Realtime uses a custom architecture that is **incompatible with vLLM**. It requires native PyTorch inference with a custom FastAPI wrapper.

#### Step 1: Install MOSS-TTS with Patches

MOSS-TTS was written for transformers 5.0 dev and requires several patches for compatibility with transformers 4.x:

```bash
cd ~/telephony-stack

# Clone MOSS-TTS repository (if not already done)
if [ ! -d "moss-tts-src" ]; then
    git clone https://github.com/OpenMOSS-Team/MOSS-TTS.git moss-tts-src
fi

# Run the installation script (applies all patches automatically)
./scripts/install-moss-tts.sh
```

**Patches Applied:**
1. `transformers.initialization` → `torch.nn.init` (doesn't exist in 4.x)
2. `rope_scaling` config fixed (needs dict format, not null)
3. `PreTrainedConfig` → `PretrainedConfig` (capitalization fixed)

#### Step 2: Download MOSS-Audio-Tokenizer (Required Codec)

```bash
# The codec is required for audio tokenization
cd ~/telephony-stack

huggingface-cli download \
    OpenMOSS-Team/MOSS-Audio-Tokenizer \
    --local-dir ~/telephony-stack/models/tts/moss-audio-tokenizer \
    --local-dir-use-symlinks False
```

#### Step 3: Start MOSS-TTS FastAPI Server

```bash
cd ~/telephony-stack
source telephony-stack-env/bin/activate

# CRITICAL: Memory configuration to prevent clashes with vLLM
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CUDA_HOME=/usr/local/cuda-13.0
export HF_HOME=~/telephony-stack/.cache/huggingface

# Run the native PyTorch FastAPI server
python tts/moss_tts_fastapi_server.py
```

**Why Native PyTorch?**
- MOSS-TTS uses a custom dual-model architecture (latent acoustic model + separate audio codec)
- Not a standard HuggingFace AutoModel class
- Requires `MossTTSRealtime` + `MOSS-Audio-Tokenizer` codec for encode/decode
- vLLM doesn't support custom audio TTS architectures

**Key Features**:
- Uses **bfloat16** (NOT float16 - avoids NaN spikes/static in audio)
- **Real-time streaming**: Yields 20ms audio chunks as they're generated
- **Zero-shot voice cloning**: Pass reference audio via `extra_body`
- OpenAI-compatible `/v1/audio/speech` endpoint

**Memory Safety**:
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` prevents memory fragmentation
- Allows PyTorch to coexist with vLLM's pre-allocated memory blocks

---

## Verification

### 1. Check Services Are Running

```bash
# Check ports
curl http://localhost:8000/health
curl http://localhost:8001/health

# List models
curl http://localhost:8000/v1/models
curl http://localhost:8001/v1/models
```

### 2. Test Nemotron LLM

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50
  }'
```

### 3. Test Voxtral ASR

```bash
# Test with audio file (requires base64 encoding)
curl -X POST http://localhost:8001/v1/audio/transcriptions \
  -H "Content-Type: multipart/form-data" \
  -F file=@test_audio.wav \
  -F model="voxtral"
```

### 4. Test MOSS-TTS (Native PyTorch)

**Test basic TTS:**
```bash
curl -X POST http://localhost:8002/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
    "input": "Hello, I am calling about your recent inquiry.",
    "voice": "default_female",
    "response_format": "pcm"
  }' \
  --output speech.pcm

# Play the audio (requires sox)
play -r 24000 -e signed -b 16 -c 1 speech.pcm
```

**Test zero-shot voice cloning:**
```bash
# Encode reference audio to base64
REF_AUDIO_B64=$(base64 -w 0 reference_speaker.wav)

curl -X POST http://localhost:8002/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
    "input": "This is spoken in the cloned voice.",
    "voice": "cloned",
    "response_format": "pcm",
    "extra_body": {
      "reference_audio": "'$REF_AUDIO_B64'"
    }
  }' \
  --output cloned_speech.pcm
```

### 4. Monitor GPU Usage

```bash
watch -n 1 nvidia-smi
```

Expected allocation:
- Nemotron: ~18-20 GB (20%)
- Voxtral: ~8-10 GB (10%)
- Free: ~44 GB (55%) for concurrent streams

---

## Troubleshooting

### Issue: `ImportError: libcudart.so.12: cannot open shared object file`

**Cause:** Pre-built vLLM wheel compiled against CUDA 12.x
**Fix:** Build vLLM from source (see section above)

### Issue: `Value error, Quantization method specified in the model config (modelopt_fp4) does not match`

**Cause:** Using `--quantization nvfp4` instead of `modelopt_fp4`
**Fix:** Use `--quantization modelopt_fp4`

### Issue: `PermissionError: [Errno 13] Permission denied: '/home/phil/.cache/huggingface/...'`

**Cause:** Previous download attempts left corrupted cache
**Fix:**
```bash
# Clear cache
sudo rm -rf ~/.cache/huggingface/hub/models--nvidia--NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4

# Use custom HF_HOME
export HF_HOME=~/telephony-stack/.cache/huggingface
```

### Issue: `Repository Not Found for url: https://huggingface.co/...`

**Cause:** HF_TOKEN not set or invalid
**Fix:**
```bash
export HF_TOKEN=your_actual_token_here
huggingface-cli login --token $HF_TOKEN
```

### Issue: `OSError: ... is not a local folder and is not a valid model identifier`

**Cause:** Model path incorrect or model not downloaded
**Fix:** Use full local path:
```bash
--model ~/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4
```

### Issue: Model loading hangs at "Loading safetensors checkpoint shards"

**Cause:** First-time loading takes time
**Solution:** Wait 2-5 minutes. Check disk I/O with `iostat -x 1`

### Issue: `ptxas fatal : Value 'sm_121a' is not defined for option 'gpu-name'`

**Cause:** Triton's bundled ptxas compiler (from CUDA 12.x) doesn't understand Blackwell (sm_121a)
**Fix:** Force Triton to use CUDA 13.0's ptxas:
```bash
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas
```

### Issue: High memory usage / OOM

**Cause:** Mamba model being treated as Transformer (KV cache allocated)
**Fix:** Ensure using `--enforce-eager` flag

---

## Quick Reference

### Directory Structure

```
~/telephony-stack/
├── models/
│   ├── llm/nemotron-3-nano-30b-nvfp4/    # 19 GB
│   ├── asr/voxtral-mini-4b-realtime/      # 17 GB
│   └── tts/moss-tts-realtime/             # 4.4 GB
├── scripts/
│   ├── start-nemotron.sh
│   ├── start-voxtral-asr.sh
│   └── start-moss-tts.sh
└── .cache/huggingface/                    # Custom cache

~/vllm-src/                                # vLLM source
~/telephony-stack-env/                     # Python venv
```

### Environment Variables

```bash
# Core (always required)
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export CUDA_HOME=/usr/local/cuda-13.0
export HF_HOME=~/telephony-stack/.cache/huggingface
export HF_TOKEN=your_token

# CRITICAL: Triton JIT compiler for Blackwell (sm_121a)
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas

# Build (only for compiling vLLM)
export TORCH_CUDA_ARCH_LIST="12.1"
export VLLM_INSTALL_PUNICA_KERNELS=1
```

### Service URLs

| Service | Port | Framework | Endpoint |
|---------|------|-----------|----------|
| Nemotron LLM | 8000 | vLLM v0.16.0 | http://localhost:8000/v1/chat/completions |
| Voxtral ASR | 8001 | vLLM v0.16.0 | http://localhost:8001/v1/audio/transcriptions |
| MOSS-TTS | 8002 | **Native PyTorch** | http://localhost:8002/v1/audio/speech |

**Note**: MOSS-TTS uses native PyTorch (FastAPI wrapper) due to its custom dual-model architecture (acoustic model + audio codec) that vLLM cannot support.

### Memory Allocation (128GB GB10)

| Component | Allocation | Notes |
|-----------|------------|-------|
| Nemotron LLM | 20% (16-20 GB) | NVFP4 quantization, Mamba - no KV cache |
| Voxtral ASR | 10% (8-10 GB) | BF16, realtime capable |
| MOSS-TTS | 15% (~12 GB) | BF16, native PyTorch, expandable segments |
| Free for calls | 55% (~55 GB) | 300+ concurrent streams |

### Final Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DGX Spark GB10 Telephony Stack (2026)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐ │
│  │ Port 8000           │  │ Port 8001           │  │ Port 8002           │ │
│  │ ─────────────────── │  │ ─────────────────── │  │ ─────────────────── │ │
│  │ Nemotron-3-Nano     │  │ Voxtral-Mini-4B     │  │ MOSS-TTS-Realtime   │ │
│  │ Framework: vLLM     │  │ Framework: vLLM     │  │ Framework: PyTorch  │ │
│  │ Quant: modelopt_fp4 │  │ Dtype: bfloat16     │  │ Dtype: bfloat16     │ │
│  │ Memory: 20%         │  │ Memory: 10%         │  │ Memory: 15%         │ │
│  │                     │  │                     │  │                     │ │
│  │ /v1/chat/completions│  │ /v1/audio/transcrip │  │ /v1/audio/speech    │ │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘ │
│                                                                             │
│  Key Features:                                                              │
│  • NVFP4 quantization for LLM (4x compression)                              │
│  • Realtime ASR with WebSocket streaming                                    │
│  • Streaming TTS with 20ms audio chunks                                     │
│  • Zero-shot voice cloning support                                          │
│                                                                             │
│  Memory Safety:                                                             │
│  • PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True (prevents vLLM clash)   │
│  • TRITON_PTXAS_PATH for Blackwell sm_121a support                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Next Steps

After successful deployment:

1. **Build Rust orchestrator** with LiveKit integration
2. **Configure 8kHz audio pipeline** for telephony
3. **Set up monitoring** (Prometheus/Grafana)
4. **Configure load balancing** for multi-node deployment

---

## Appendix: Why Native PyTorch for MOSS-TTS?

### The Architecture Challenge

MOSS-TTS-Realtime uses a **dual-model architecture** that vLLM cannot support:

1. **Latent Acoustic Model**: Qwen3-based backbone generating semantic audio representations
2. **Audio Codec**: MOSS-Audio-Tokenizer for encoding/decoding raw waveform

```
Text Input → Acoustic Model → Latent Tokens → Codec Decoder → PCM Audio
     ↑                                            ↓
     └──────── Reference Audio (voice cloning) ───┘
```

### Why vLLM Fails

```
Error: Transformers does not recognize this architecture (moss_tts_realtime)
```

- vLLM only supports standard HuggingFace AutoModel classes
- MOSS-TTS uses custom `MossTTSRealtime` class with `MossTTSRealtimeProcessor`
- Requires separate codec model for audio tokenization
- Uses custom streaming inference with 16-channel audio codes

### The Solution: Native PyTorch + FastAPI

```
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Server (Port 8002)                                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Native PyTorch Inference                              │  │
│  │  • MossTTSRealtime.from_pretrained()                   │  │
│  │  • StreamingResponse for real-time chunks              │  │
│  │  • 20ms audio latency (vs 1-2s batch wait)             │  │
│  └───────────────────────────────────────────────────────┘  │
│                        ↓                                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  OpenAI-Compatible API                                 │  │
│  │  POST /v1/audio/speech                                 │  │
│  │  • input: text                                         │  │
│  │  • extra_body.reference_audio: base64 voice clone      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Memory Coexistence with vLLM

vLLM pre-allocates large memory blocks. Native PyTorch uses `expandable_segments:True` to dynamically grow without fragmentation:

```bash
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

---

**Document Version:** 1.1  
**Last Updated:** 2026-03-01  
**Target:** DGX Spark (GB10), vLLM v0.16.0, CUDA 13.0, MOSS-TTS Native
