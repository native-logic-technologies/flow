#!/bin/bash
# Dream Stack Launch Script - Llama.cpp Omni-Ear Edition
# DGX Spark (GB10) - Hybrid Specialist Architecture

echo "╔═══════════════════════════════════════════════════════════════════════════════╗"
echo "║                    🚀 DREAM STACK LAUNCHER                                    ║"
echo "║              Hybrid Specialist Architecture (GB10)                            ║"
echo "╚═══════════════════════════════════════════════════════════════════════════════╝"
echo ""

cd /home/phil/telephony-stack
source /home/phil/telephony-stack-env/bin/activate

# Kill any existing processes
pkill -9 -f "llama-server.*8001" 2>/dev/null || true
pkill -9 -f "vllm.*8000" 2>/dev/null || true
pkill -9 -f "moss_tts" 2>/dev/null || true
sleep 3

echo "🎙️  Starting MOSS-TTS (Voice) on port 8002..."
cd /home/phil/telephony-stack/tts
PORT=8002 nohup $VIRTUAL_ENV/bin/python moss_tts_fastapi_server.py > /tmp/moss.log 2>&1 &
MOSS_PID=$!

echo "🧠 Starting Nemotron Brain on port 8000..."
cd /home/phil/telephony-stack
export TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas
export CUDA_HOME=/usr/local/cuda-13.0
nohup $VIRTUAL_ENV/bin/python -m vllm.entrypoints.openai.api_server \
    --model /home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4 \
    --quantization modelopt_fp4 \
    --port 8000 \
    --gpu-memory-utilization 0.4 \
    --max-model-len 4096 \
    > /tmp/brain.log 2>&1 &
BRAIN_PID=$!

echo "👂 Starting Llama-Omni Ear on port 8001..."
cd /home/phil/telephony-stack
nohup ./llama.cpp/build/bin/llama-server \
    --model ./models/Qwen2.5-Omni-7B-q8_0.gguf \
    --port 8001 \
    --n-gpu-layers 99 \
    --ctx-size 4096 \
    --threads 8 \
    --logit-bias "13708-100,766-100,29-100,522-100,26865-100,19895-100,82260-100" \
    > /tmp/llama_ear.log 2>&1 &
EAR_PID=$!

echo ""
echo "⏳ Waiting for services to start..."
echo ""

# Wait for all services
for i in {1..60}; do
    sleep 3
    
    moss=$(curl -s http://localhost:8002/health 2>/dev/null && echo "✅" || echo "⏳")
    brain=$(curl -s http://localhost:8000/health 2>/dev/null && echo "✅" || echo "⏳")
    ear=$(curl -s http://localhost:8001/health 2>/dev/null && echo "✅" || echo "⏳")
    
    echo -ne "\rMOSS: $moss | Nemotron: $brain | Llama-Omni: $ear"
    
    if [[ "$moss" == "✅" && "$brain" == "✅" && "$ear" == "✅" ]]; then
        echo ""
        echo ""
        echo "🎉 ALL SERVICES ONLINE!"
        break
    fi
done

echo ""
echo "╔═══════════════════════════════════════════════════════════════════════════════╗"
echo "║                    🏆 DREAM STACK READY                                       ║"
echo "╚═══════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "  🎙️  MOSS-TTS:    http://localhost:8002"
echo "  🧠 Nemotron:     http://localhost:8000"
echo "  👂 Llama-Omni:   http://localhost:8001"
echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"

# Show VRAM
nvidia-smi | grep -E "Processes|MiB" | head -10
