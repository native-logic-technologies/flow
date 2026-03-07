#!/bin/bash
# Start Full Stack with Strict VRAM Partitioning for DGX Spark (128GB)

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  CleanS2S Stack Launcher - Strict VRAM Partitioning               ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Kill existing processes
echo "🧹 Cleaning up..."
pkill -9 -f "vllm|asr_nemotron|telephony|moss_tts|llama-server" 2>/dev/null || true
sleep 3

# Environment setup
export HF_HOME=/tmp/hf_cache
export CUDA_HOME=/usr/local/cuda-13.0
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export VLLM_ATTENTION_BACKEND=FLASHINFER
export TRITON_PTXAS_PATH=$CUDA_HOME/bin/ptxas
export CUDA_VISIBLE_DEVICES=0

PYTHON_VENV=/home/phil/telephony-stack-env/bin/python
cd /home/phil/telephony-stack

echo ""
echo "┌───────────────────────────────────────────────────────────────────┐"
echo "│  VRAM Budget (128GB Total)                                        │"
echo "├───────────────────────────────────────────────────────────────────┤"
echo "│  🧠 Brain (Nemotron 30B)    │ 35GB  │ gpu-memory-utilization 0.25 │"
echo "│  🎤 ASR (Nemotron Speech)   │ 10GB  │ Fixed size                │"
echo "│  🗣️  Voice (llama.cpp)      │ 15GB  │ Q8_0 GGUF                 │"
echo "│  📞 Telephony               │ ~2GB  │ CPU mostly                │"
echo "│  🔄 Buffer                  │ 66GB  │ Safety margin             │"
echo "└───────────────────────────────────────────────────────────────────┘"
echo ""

# 1. ASR (Port 8004) - Start first as it's smallest
echo "🎤 Starting ASR (Nemotron Speech Streaming)..."
nohup $PYTHON_VENV asr_nemotron_server.py > /tmp/asr.log 2>&1 &
echo "   PID: $!"
sleep 5

# 2. TTS via llama.cpp (Port 8002) - MOSS-TTS GGUF
echo "🗣️  Starting TTS (llama.cpp MOSS-TTS Q8_0)..."
nohup /home/phil/telephony-stack/llama.cpp/build/bin/llama-server \
  -m /home/phil/telephony-stack/models/tts-gguf/MOSS_TTS_backbone_q8_0.gguf \
  --port 8002 \
  -ngl 99 \
  --host 0.0.0.0 \
  > /tmp/llama_tts.log 2>&1 &
echo "   PID: $!"
sleep 10

# 3. Brain (Port 8000) - Nemotron 30B with STRICT VRAM limit
echo "🧠 Starting Brain (Nemotron 30B-A3B NVFP4)..."
echo "   ⚠️  Strict limit: gpu-memory-utilization 0.25 (32GB max)"
nohup $PYTHON_VENV -m vllm.entrypoints.openai.api_server \
  --model /home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4 \
  --quantization modelopt_fp4 \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization 0.25 \
  --max-model-len 4096 \
  --enforce-eager \
  --port 8000 \
  --trust-remote-code \
  > /tmp/brain.log 2>&1 &
echo "   PID: $!"
sleep 15

# 4. Telephony (Port 8003)
echo "📞 Starting Telephony..."
nohup $PYTHON_VENV telephony_http_streaming.py > /tmp/telephony.log 2>&1 &
echo "   PID: $!"
sleep 2

echo ""
echo "⏳ Waiting for all services to be ready..."
echo ""

# Wait loop
for i in {1..120}; do
  B=$(curl -s http://localhost:8000/health 2>/dev/null && echo "✅" || echo "⏳")
  A=$(curl -s http://localhost:8004/health 2>/dev/null && echo "✅" || echo "⏳")
  V=$(curl -s http://localhost:8002/health 2>/dev/null && echo "✅" || echo "⏳")
  T=$(curl -s http://localhost:8003/health 2>/dev/null && echo "✅" || echo "⏳")
  
  printf "\rBrain: $B | ASR: $A | Voice: $V | Telephony: $T"
  
  if [[ "$B" == "✅" && "$A" == "✅" && "$V" == "✅" && "$T" == "✅" ]]; then
    echo ""
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║   🎉 FULL STACK READY!                                     ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    echo "📞 Call: https://cleans2s.voiceflow.cloud/twilio/inbound"
    echo ""
    nvidia-smi | grep -E "python|llama|MiB" | head -6
    exit 0
  fi
  
  sleep 2
done

echo ""
echo ""
echo "⚠️  Some services still loading. Check logs:"
echo "  Brain: tail -5 /tmp/brain.log"
echo "  ASR: tail -5 /tmp/asr.log"
echo "  TTS: tail -5 /tmp/llama_tts.log"
echo "  Telephony: tail -5 /tmp/telephony.log"
