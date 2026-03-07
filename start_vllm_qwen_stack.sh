#!/bin/bash
# Start Full Emotional Stack with vLLM-Qwen Docker
# Uses: vllm/vllm-openai@sha256:b6fcb1a19dad25e60e3e91e98ed36163978778fff2d82416c773ca033aa857eb

set -e

cd /home/phil/telephony-stack

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     CleanS2S - vLLM Qwen Emotional Stack                       ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  🐳 vLLM Docker: sha256:b6fcb1a... (ARM64/Qwen)               ║"
echo "║                                                                ║"
echo "║  Services:                                                     ║"
echo "║    🧠 Brain:  Qwen3.5-9B     :8000  (vLLM Docker)             ║"
echo "║    🎤 ASR:    Qwen2.5-Omni   :8001  (Emotion Extraction)      ║"
echo "║    🎙️  TTS:    MOSS-Realtime  :8002  (Emotional Voice)         ║"
echo "║    📞 Bridge: Emotional      :8080  (Orchestrator)            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Configuration
VLLM_IMAGE="vllm-qwen:latest"
BRAIN_MODEL="Qwen/Qwen3.5-9B-Instruct"
# Or use Nemotron: BRAIN_MODEL="nvidia/Nemotron-3-Nano-30B-A3B-NVFP4"

# Kill existing processes
echo "🧹 Cleaning up..."
docker stop qwen35-9b nemotron brain 2>/dev/null || true
docker rm qwen35-9b nemotron brain 2>/dev/null || true
pkill -f "asr_emotion_server" 2>/dev/null || true
pkill -f "tts_moss_realtime" 2>/dev/null || true
pkill -f "emotional_orchestrator" 2>/dev/null || true
sleep 2

# Check VRAM
echo ""
echo "📊 Initial VRAM:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "   %.1f GB / %.1f GB\n", $1/1024, $2/1024}'

echo ""
echo "🐳 Starting vLLM with Qwen3.5-9B..."
docker run -d --gpus all --name qwen35-9b \
    --network host \
    -v /home/phil/telephony-stack/models:/models:ro \
    -e HF_HOME=/tmp/hf_cache \
    $VLLM_IMAGE \
    --model /models/quantized/Qwen3.5-9B-NVFP4 \
    --quantization modelopt_fp4 \
    --kv-cache-dtype fp8 \
    --tensor-parallel-size 1 \
    --gpu-memory-utilization 0.7 \
    --max-model-len 4096 \
    --enforce-eager \
    --port 8000 \
    --trust-remote-code \
    2>&1 | tail -5

echo "   Waiting for vLLM to start (this may take 60s)..."
for i in {1..120}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo ""
        echo "   ✅ vLLM ready on port 8000"
        break
    fi
    sleep 1
    if [ $i -eq 120 ]; then
        echo ""
        echo "   ❌ vLLM failed to start"
        docker logs qwen35-9b --tail 50
        exit 1
    fi
    if [ $((i % 10)) -eq 0 ]; then
        echo -n "."
    fi
done

echo ""
echo "📊 VRAM after vLLM:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "   %.1f GB / %.1f GB\n", $1/1024, $2/1024}'

# Start ASR
echo ""
echo "🎤 Starting ASR (Qwen2.5-Omni with emotion)..."
export PYTHONPATH=/home/phil/telephony-stack:$PYTHONPATH
/home/phil/telephony-stack-env/bin/python asr_emotion_server.py > /tmp/asr.log 2>&1 &
ASR_PID=$!
echo $ASR_PID > /tmp/asr.pid

for i in {1..60}; do
    if curl -s http://localhost:8001/health > /dev/null 2>&1; then
        echo "   ✅ ASR ready on port 8001"
        break
    fi
    sleep 1
    if [ $i -eq 60 ]; then
        echo "   ❌ ASR failed to start"
        exit 1
    fi
done

# Start TTS
echo ""
echo "🎙️  Starting TTS (MOSS-TTS-Realtime with emotion)..."
/home/phil/telephony-stack-env/bin/python tts_moss_realtime_server.py > /tmp/tts.log 2>&1 &
TTS_PID=$!
echo $TTS_PID > /tmp/tts.pid

for i in {1..60}; do
    if curl -s http://localhost:8002/health > /dev/null 2>&1; then
        echo "   ✅ TTS ready on port 8002"
        break
    fi
    sleep 1
    if [ $i -eq 60 ]; then
        echo "   ❌ TTS failed to start"
        exit 1
    fi
done

# Start Orchestrator
echo ""
echo "📞 Starting Emotional Orchestrator..."
/home/phil/telephony-stack-env/bin/python emotional_orchestrator.py > /tmp/orchestrator.log 2>&1 &
ORCH_PID=$!
echo $ORCH_PID > /tmp/orchestrator.pid

for i in {1..30}; do
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "   ✅ Orchestrator ready on port 8080"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo "   ❌ Orchestrator failed to start"
        exit 1
    fi
done

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    ✅ Stack Ready!                             ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  🧠 Brain:   http://localhost:8000/health (vLLM Qwen)         ║"
echo "║  🎤 ASR:     http://localhost:8001/health                     ║"
echo "║  🎙️  TTS:     http://localhost:8002/health                     ║"
echo "║  📞 Bridge:  http://localhost:8080/health                     ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  Logs:                                                         ║"
echo "║    docker logs -f qwen35-9b   (Brain)                         ║"
echo "║    tail -f /tmp/asr.log       (ASR)                           ║"
echo "║    tail -f /tmp/tts.log       (TTS)                           ║"
echo "║    tail -f /tmp/orchestrator.log (Bridge)                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"

echo ""
echo "📊 Final VRAM:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "   %.1f GB / %.1f GB\n", $1/1024, $2/1024}'

echo ""
read -p "Press Enter to keep running (logs will show) or Ctrl+C to exit..."
wait
