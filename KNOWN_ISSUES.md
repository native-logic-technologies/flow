# Known Issues and Workarounds

## 1. MOSS-TTS Voice Cloning - torchcodec Version Mismatch

### Symptom
```
Warning: Failed to encode reference audio: TorchCodec is required for 
load_with_torchcodec. Please install torchcodec to use this function.
```

### Cause
MOSS-TTS's MOSS-Audio-Tokenizer requires `torchcodec==0.8.1`, but this version 
is not available in PyPI. The installed version (0.0.0.dev0) is incompatible.

### Impact
- ✅ Core TTS works normally
- ❌ Zero-shot voice cloning disabled
- Default voice used instead of cloned voice

### Workaround Options

**Option 1: Use Default Voice (Current)**
TTS will work with default voice. Voice cloning is not available.

**Option 2: Manual Voice File Loading (Advanced)**
Pre-encode your reference audio to tokens and pass directly:

```python
# Pre-encode reference audio using MOSS-TTS CLI
python -c "
from mossttsrealtime import MossTTSRealtime, MossTTSRealtimeProcessor
from transformers import AutoModel
import torch

# Load codec
codec = AutoModel.from_pretrained('OpenMOSS-Team/MOSS-Audio-Tokenizer', trust_remote_code=True)

# Load your audio (WAV, 16kHz, mono)
import torchaudio
wav, sr = torchaudio.load('your_voice.wav')
if sr != 16000:
    wav = torchaudio.functional.resample(wav, sr, 16000)

# Encode to tokens
with torch.no_grad():
    codes = codec.encode(wav.unsqueeze(0))
    
# Save tokens
torch.save(codes, 'your_voice_tokens.pt')
print('Tokens saved!')
"
```

**Option 3: Build torchcodec from Source**
```bash
# Clone and build specific version
git clone https://github.com/pytorch/torchcodec.git
cd torchcodec
git checkout v0.8.1  # If tag exists
pip install .
```

### Status
- 🔧 Pending: Waiting for torchcodec 0.8.1 release on PyPI
- 🔧 Alternative: Modify MOSS-TTS to use torchaudio instead of torchcodec

## 2. First-Run TTFT Warmup (Nemotron LLM)

### Symptom
First API call to Nemotron takes 30+ seconds.

### Cause
- CUDA kernel compilation/JIT on first inference
- Model weight loading to GPU
- Triton cache warming

### Workaround
Run a warmup query on startup:

```bash
# In start-nemotron.sh, add after server startup:
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "'"$MODEL_PATH"'", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}' \
  > /dev/null 2>&1 &
```

### Status
- ✅ Mitigated: Clean chat template reduces TTFT significantly
- ✅ Expected: First call slow, subsequent calls <100ms

## 3. PyTorch Version Warnings

### Symptom
```
UserWarning: PyTorch version mismatch
moss-tts requires torch==2.9.1+cu128, but you have torch 2.9.1+cu130
```

### Cause
MOSS-TTS package specifies strict PyTorch versions in its setup.py.

### Impact
- ⚠️ Warnings appear but functionality works
- No observed issues with CUDA 13.0 (cu130)

### Status
- ✅ Ignorable: Warnings don't affect runtime
- ✅ Working: CUDA 13.0 with PyTorch 2.9.1+cu130 is functional

## 4. DeepFilterNet Version

### Symptom
```
deep_filter = "0.2.5"  # Latest available
```

### Expected vs Available
- Expected: v0.5.6 with tract backend
- Available: v0.2.5

### Impact
- ✅ Noise suppression still works
- ⚠️ May have slightly higher latency than v0.5.6

### Status
- ✅ Acceptable: Current version functional
- 🔧 Watch for v0.5.6 release on crates.io

---

## Reporting New Issues

Please report issues to: https://github.com/native-logic-technologies/flow/issues

Include:
1. Terminal output / logs
2. Steps to reproduce
3. Expected vs actual behavior
4. DGX Spark environment details
