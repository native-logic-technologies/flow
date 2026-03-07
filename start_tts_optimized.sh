#!/bin/bash
# Start MOSS-TTS with Blackwell optimizations

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  MOSS-TTS Blackwell Optimized Launcher                             ║"
echo "╚════════════════════════════════════════════════════════════════════╝"

# Kill any existing TTS on port 8002
pkill -9 -f "moss_tts_fastapi_server" 2>/dev/null || true
sleep 2

# Blackwell Fast-Path Variables
echo "Setting Blackwell optimizations..."
export CUDA_HOME=/usr/local/cuda-13.0
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export VLLM_ATTENTION_BACKEND=FLASHINFER
export TRITON_PTXAS_PATH=$CUDA_HOME/bin/ptxas
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CUDA_VISIBLE_DEVICES=0

cd /home/phil/telephony-stack

echo ""
echo "Launching MOSS-TTS on Port 8002..."
nohup /home/phil/telephony-stack-env/bin/python tts/moss_tts_fastapi_server.py \
  --port 8002 --voices-dir ./voices \
  > /tmp/moss_voice_optimized.log 2>&1 &

PID=$!
echo "PID: $PID"

echo ""
echo "Waiting for TTS to boot (~60s for compilation)..."
for i in {1..90}; do
  sleep 2
  if curl -s http://localhost:8002/health > /dev/null 2>&1; then
    echo ""
    echo "✅ MOSS-TTS ready with Blackwell optimizations!"
    echo ""
    grep -E "compiled|Compiled|bfloat|Bfloat" /tmp/moss_voice_optimized.log | tail -3
    exit 0
  fi
  if [ $((i % 10)) -eq 0 ]; then
    echo "  ...$((i*2))s (torch.compile takes time on first run)"
  fi
done

echo ""
echo "⚠️  Timeout. Check logs:"
tail -20 /tmp/moss_voice_optimized.log
