#!/bin/bash
# Start MOSS-TTS llama.cpp backend server

cd /home/phil/telephony-stack

# Set up environment
export PYTHONPATH=/home/phil/telephony-stack/moss-tts-src:$PYTHONPATH
export LD_LIBRARY_PATH=/home/phil/telephony-stack/llama.cpp/build/lib:$LD_LIBRARY_PATH

# Verify model files exist
echo "Verifying model files..."
if [ ! -f "/home/phil/telephony-stack/models/tts-gguf/MOSS_TTS_backbone_q8_0.gguf" ]; then
    echo "❌ GGUF model not found!"
    exit 1
fi

if [ ! -d "/home/phil/telephony-stack/models/tts-gguf/embeddings" ]; then
    echo "❌ Embeddings directory not found!"
    exit 1
fi

if [ ! -d "/home/phil/telephony-stack/models/tts-gguf/lm_heads" ]; then
    echo "❌ LM heads directory not found!"
    exit 1
fi

echo "✅ All model files present"
echo ""
echo "🚀 Starting MOSS-TTS llama.cpp server on port 5002..."
echo "   - GGUF Backbone: Q8_0 quantized (8.2GB)")
echo "   - GPU Layers: 99 (full offloading)")
echo "   - Embeddings: NumPy CPU memory"
echo "   - LM Heads: NumPy CPU compute"
echo "   - Audio Tokenizer: ONNX Runtime"
echo ""

exec /home/phil/telephony-stack-env/bin/python tts_llama_server.py 2>&1
