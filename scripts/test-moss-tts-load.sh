#!/bin/bash
# =============================================================================
# Quick test to verify MOSS-TTS model loading works
# =============================================================================

set -e

source ~/telephony-stack-env/bin/activate

export CUDA_HOME=/usr/local/cuda-13.0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME="${HF_HOME:-$HOME/telephony-stack/.cache/huggingface}"

cd ~/telephony-stack

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Testing MOSS-TTS Model Loading                                    ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

python -c "
import sys
sys.path.insert(0, 'moss-tts-src/moss_tts_realtime')
sys.path.insert(0, 'moss-tts-src')

import torch
from transformers import AutoTokenizer, AutoModel
from mossttsrealtime import MossTTSRealtime, MossTTSRealtimeProcessor

print('Loading MOSS-TTS model...')
print(f'PyTorch: {torch.__version__}')
print(f'CUDA: {torch.version.cuda}')
print(f'Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"CPU\"}')
print()

device = 'cuda' if torch.cuda.is_available() else 'cpu'
model_path = '$HOME/telephony-stack/models/tts/moss-tts-realtime'

# Load tokenizer first (fast)
print('Loading tokenizer...')
tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
print(f'✓ Tokenizer loaded: {len(tokenizer)} tokens')

# Load model (this will take time)
print()
print('Loading MOSS-TTS model (4.4GB, this may take 30-60 seconds)...')
model = MossTTSRealtime.from_pretrained(
    model_path,
    attn_implementation='sdpa',
    torch_dtype=torch.bfloat16,
    trust_remote_code=True
).to(device)
print(f'✓ Model loaded: {sum(p.numel() for p in model.parameters())/1e6:.1f}M parameters')

# Load codec
print()
print('Loading MOSS-Audio-Tokenizer codec...')
codec_path = '$HOME/telephony-stack/models/tts/moss-audio-tokenizer'
codec = AutoModel.from_pretrained(codec_path, trust_remote_code=True).eval().to(device)
print('✓ Codec loaded')

print()
print('╔════════════════════════════════════════════════════════════════════╗')
print('║  ✅ All models loaded successfully!                                ║')
print('╚════════════════════════════════════════════════════════════════════╝')
"
