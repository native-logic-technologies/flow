# MOSS-TTS-Realtime Deployment Plan

## Model Information

- **Repository**: https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Realtime
- **Type**: Text-to-Speech (TTS) with Realtime Streaming
- **Architecture**: Novel/non-standard (sensitive to quantization)
- **Recommended Precision**: FP16 or BF16 (standard, no quantization)
- **Target**: Port 8002

## Key Considerations

### 1. No Quantization
Unlike Nemotron (NVFP4), MOSS-TTS uses a novel architecture that's sensitive to quantization. We must use:
- `--dtype float16` or `--dtype bfloat16`
- NO `--quantization` flag
- Higher GPU memory usage expected (~12-15 GB)

### 2. Architecture Unknown
MOSS-TTS may use:
- Custom attention mechanisms
- Flow-based or diffusion-based generation
- Non-standard transformer variants
- Potential issues with vLLM's standard assumptions

### 3. Realtime Requirements
- Streaming audio output
- Low latency (<200ms per chunk)
- 8kHz or 16kHz output (telephony)

## Deployment Steps

### Step 1: Download Model

```bash
source ~/telephony-stack-env/bin/activate
export HF_HOME=~/telephony-stack/.cache/huggingface

huggingface-cli download \
    OpenMOSS-Team/MOSS-TTS-Realtime \
    --local-dir ~/telephony-stack/models/tts/moss-tts-realtime \
    --local-dir-use-symlinks False \
    --token $HF_TOKEN
```

### Step 2: Inspect Model Config

Before deployment, inspect:
```bash
cat ~/telephony-stack/models/tts/moss-tts-realtime/config.json
```

Check for:
- `architectures` field
- `torch_dtype` recommendation
- `max_position_embeddings`
- Custom quantization config

### Step 3: Test Load

```bash
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas
export VLLM_WORKER_MULTIPROC_METHOD=spawn

python -m vllm.entrypoints.openai.api_server \
    --model ~/telephony-stack/models/tts/moss-tts-realtime \
    --dtype float16 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.15 \
    --enforce-eager \
    --trust-remote-code \
    --port 8002
```

### Step 4: Fallback Options

If vLLM fails to load MOSS-TTS (due to custom architecture):

**Option A: Native PyTorch Inference**
```python
# Use Transformers directly instead of vLLM
from transformers import AutoModel, AutoTokenizer
import torch

model = AutoModel.from_pretrained(
    "~/telephony-stack/models/tts/moss-tts-realtime",
    torch_dtype=torch.float16,
    device_map="auto",
    trust_remote_code=True
)
```

**Option B: Custom FastAPI Wrapper**
Create a simple FastAPI service wrapping the native model.

**Option C: Use Alternative TTS**
If MOSS-TTS is incompatible with vLLM, consider:
- Coqui TTS (MOSHI-compatible)
- StyleTTS 2
- MeloTTS

## Resource Allocation

| Component | Memory | Notes |
|-----------|--------|-------|
| Nemotron LLM | 20% (18.65 GB) | ✅ Running |
| Voxtral ASR | 10% (~8-10 GB) | ✅ Running |
| MOSS-TTS | 15% (~12-15 GB) | FP16, no quantization |
| **Free** | **55%** | For 300+ concurrent streams |

## Risk Mitigation

### Risk 1: vLLM Incompatibility
**Mitigation**: Test with `--load-format dummy` first, then native PyTorch fallback.

### Risk 2: High Memory Usage
**Mitigation**: If >15 GB, reduce to `--gpu-memory-utilization 0.12` or use CPU offloading.

### Risk 3: Slow Inference
**Mitigation**: Enable CUDA graphs if model supports it (remove `--enforce-eager` for test).

## Success Criteria

- [ ] Model downloads successfully
- [ ] Loads without errors
- [ ] First inference request succeeds
- [ ] Latency <200ms per audio chunk
- [ ] Memory usage <15 GB
- [ ] API responds on port 8002

## Next Actions

1. Attempt model download
2. Inspect config.json
3. Attempt vLLM load
4. If fails, implement native PyTorch fallback
5. Create 8kHz vocoder adapter if needed
