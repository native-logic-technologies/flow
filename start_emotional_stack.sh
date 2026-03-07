#!/bin/bash
# Start the full Emotional Metadata Bridge stack
# ASR -> Brain -> TTS with emotion propagation

set -e

cd /home/phil/telephony-stack

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     CleanS2S - Emotional Metadata Bridge Stack                ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  🎤 ASR:    Qwen2.5-Omni  :8001  [Emotion Extraction]         ║"
echo "║  🧠 Brain:  Qwen3.5-9B    :8000  [Emotional Reasoning]        ║"
echo "║  🎙️  TTS:    MOSS-Realtime :8002  [Emotional Voice Cloning]   ║"
echo "║  📞 Bridge: Emotional     :8080  [Metadata Orchestrator]      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Kill existing processes
echo "🧹 Cleaning up existing processes..."
pkill -f "asr_emotion_server" 2>/dev/null || true
pkill -f "brain_emotion_server" 2>/dev/null || true
pkill -f "tts_moss_realtime" 2>/dev/null || true
pkill -f "emotional_orchestrator" 2>/dev/null || true
sleep 2

# Check VRAM
echo ""
echo "📊 Initial VRAM usage:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "   %.1f GB / %.1f GB\n", $1/1024, $2/1024}'
echo ""

# Function to wait for service
wait_for_service() {
    local name=$1
    local url=$2
    local max_wait=${3:-60}
    
    echo -n "   Waiting for $name..."
    for i in $(seq 1 $max_wait); do
        if curl -s "$url" > /dev/null 2>&1; then
            echo " ✅"
            return 0
        fi
        sleep 1
        echo -n "."
    done
    echo " ❌ Timeout"
    return 1
}

# Start ASR (Emotion-aware)
echo "🎤 Starting ASR (Qwen2.5-Omni with emotion extraction)..."
export PYTHONPATH=/home/phil/telephony-stack:$PYTHONPATH
/home/phil/telephony-stack-env/bin/python asr_emotion_server.py > /tmp/asr.log 2>&1 &
ASR_PID=$!
echo $ASR_PID > /tmp/asr.pid
wait_for_service "ASR" "http://localhost:8001/health" 120 || exit 1

# Start Brain (Emotional reasoning)
echo ""
echo "🧠 Starting Brain (Qwen3.5-9B with emotional reasoning)..."
/home/phil/telephony-stack-env/bin/python brain_emotion_server.py > /tmp/brain.log 2>&1 &
BRAIN_PID=$!
echo $BRAIN_PID > /tmp/brain.pid
wait_for_service "Brain" "http://localhost:8000/health" 120 || exit 1

# Start TTS (MOSS-TTS-Realtime with emotional voices)
echo ""
echo "🎙️  Starting TTS (MOSS-TTS-Realtime with emotion caching)..."
/home/phil/telephony-stack-env/bin/python tts_moss_realtime_server.py > /tmp/tts.log 2>&1 &
TTS_PID=$!
echo $TTS_PID > /tmp/tts.pid
wait_for_service "TTS" "http://localhost:8002/health" 120 || exit 1

# Show VRAM after model loading
echo ""
echo "📊 VRAM after model loading:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "   %.1f GB / %.1f GB\n", $1/1024, $2/1024}'
echo ""

# Start Emotional Orchestrator
echo "📞 Starting Emotional Orchestrator Bridge..."
/home/phil/telephony-stack-env/bin/python emotional_orchestrator.py > /tmp/orchestrator.log 2>&1 &
ORCH_PID=$!
echo $ORCH_PID > /tmp/orchestrator.pid
wait_for_service "Orchestrator" "http://localhost:8080/health" 30 || exit 1

# Summary
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    ✅ Stack Ready!                             ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  Services:                                                     ║"
echo "║    🎤 ASR:     http://localhost:8001/health                   ║"
echo "║    🧠 Brain:   http://localhost:8000/health                   ║"
echo "║    🎙️  TTS:     http://localhost:8002/health                   ║"
echo "║    📞 Bridge:  http://localhost:8080/health                   ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  Test Commands:                                                ║"
echo "║    curl http://localhost:8001/health                          ║"
echo "║    curl http://localhost:8000/emotions                        ║"
echo "║    curl http://localhost:8002/voices                          ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  Logs:                                                         ║"
echo "║    tail -f /tmp/asr.log      (ASR)                            ║"
echo "║    tail -f /tmp/brain.log    (Brain)                          ║"
echo "║    tail -f /tmp/tts.log      (TTS)                            ║"
echo "║    tail -f /tmp/orchestrator.log (Bridge)                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Keep script running
wait
