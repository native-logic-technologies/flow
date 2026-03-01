#!/bin/bash
# =============================================================================
# Install MOSS-TTS Native Package and Dependencies
# This is REQUIRED since vLLM doesn't support the custom moss_tts_realtime architecture
# 
# NOTE: Applies multiple patches for transformers 4.x compatibility
# =============================================================================

set -e

source ~/telephony-stack-env/bin/activate

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Installing MOSS-TTS Native Package                                ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

cd ~/telephony-stack

# ============================================================================
# PATCH 1: MOSS-TTS source code for transformers 4.x
# ============================================================================
echo "Patching MOSS-TTS for transformers 4.x compatibility..."

# Fix: transformers.initialization doesn't exist in 4.x, use torch.nn.init
sed -i 's/from transformers import initialization as init/import torch.nn.init as init/' \
    moss-tts-src/moss_tts_realtime/mossttsrealtime/modeling_mossttsrealtime.py
echo "✓ Patched modeling_mossttsrealtime.py (initialization import)"

# ============================================================================
# PATCH 2: MOSS-TTS config for rope_scaling
# ============================================================================
echo ""
echo "Patching MOSS-TTS config for rope_scaling compatibility..."
python3 << 'PYEOF'
import json
config_path = "models/tts/moss-tts-realtime/config.json"

with open(config_path, 'r') as f:
    config = json.load(f)

# Fix rope_scaling in local_config - needs to be a dict, not null
if 'rope_scaling' not in config.get('local_config', {}) or config['local_config'].get('rope_scaling') is None:
    config['local_config']['rope_scaling'] = {'type': 'linear', 'factor': 1.0}
    print("  ✓ Fixed rope_scaling in local_config")

# Add rope_type if missing
if 'rope_type' not in config.get('local_config', {}):
    config['local_config']['rope_type'] = 'linear'
    print("  ✓ Added rope_type to local_config")

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)
print("✓ Config patched successfully")
PYEOF

# ============================================================================
# PATCH 3: MOSS-Audio-Tokenizer codec config
# ============================================================================
echo ""
echo "Patching MOSS-Audio-Tokenizer codec for transformers 4.x..."
sed -i 's/PreTrainedConfig/PretrainedConfig/g' \
    models/tts/moss-audio-tokenizer/configuration_moss_audio_tokenizer.py
echo "✓ Patched codec configuration (PreTrainedConfig → PretrainedConfig)"

# ============================================================================
# Install MOSS-TTS package
# ============================================================================
echo ""
echo "Installing MOSS-TTS package (without dependencies)..."
echo "Note: PyTorch already installed (2.9.1+cu130), skipping torch/torchaudio deps"
echo ""

cd moss-tts-src
pip install -e . --no-deps

# ============================================================================
# Install additional dependencies
# ============================================================================
echo ""
echo "Installing additional MOSS-TTS dependencies..."

pip install \
    "transformers>=4.48.0" \
    "safetensors>=0.4.0" \
    "numpy>=1.24.0" \
    "orjson>=3.10.0" \
    "tqdm>=4.65.0" \
    "PyYAML>=6.0" \
    "einops>=0.7.0" \
    "scipy>=1.11.0" \
    "librosa>=0.10.0" \
    "tiktoken>=0.7.0" \
    psutil \
    packaging \
    ninja \
    gradio \
    fastapi \
    uvicorn \
    "pydantic>=2.0"

# ============================================================================
# Download MOSS-Audio-Tokenizer if needed
# ============================================================================
echo ""
echo "Checking MOSS-Audio-Tokenizer (required codec)..."
if [ ! -f "$HOME/telephony-stack/models/tts/moss-audio-tokenizer/model.safetensors.index.json" ]; then
    huggingface-cli download \
        OpenMOSS-Team/MOSS-Audio-Tokenizer \
        --local-dir ~/telephony-stack/models/tts/moss-audio-tokenizer \
        --local-dir-use-symlinks False
    # Re-apply patch after download
    sed -i 's/PreTrainedConfig/PretrainedConfig/g' \
        ~/telephony-stack/models/tts/moss-audio-tokenizer/configuration_moss_audio_tokenizer.py
    echo "✓ Codec downloaded and patched"
else
    echo "✓ Codec already downloaded"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ MOSS-TTS installation complete!                                ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Applied patches:"
echo "  • torch.nn.init (replaced transformers.initialization)"
echo "  • rope_scaling config (added dict format)"
echo "  • PretrainedConfig (fixed capitalization)"
echo ""
echo "To start the server: ./scripts/start-moss-tts-native.sh"
