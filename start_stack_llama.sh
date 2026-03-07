#!/bin/bash
# Start full telephony stack with llama.cpp TTS backend

set -e

cd /home/phil/telephony-stack

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     CleanS2S Telephony Stack - llama.cpp Backend            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Kill existing processes
echo "🧹 Cleaning up existing processes..."
pkill -f "tts_llama_server.py" 2>/dev/null || true
pkill -f "telephony_bridge.py" 2>/dev/null || true
pkill -f "python.*brain" 2>/dev/null || true
sleep 1

# Check VRAM usage
echo ""
echo "📊 Current VRAM usage:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader | while read line; do
    echo "   GPU: $line"
done
echo ""

# Start ASR (NVIDIA Riva/Nemotron Speech)
echo "🎤 Starting ASR (Nemotron Speech)..."
if docker ps | grep -q "nvidia/riva-speech"; then
    echo "   ✓ ASR container already running"
else
    echo "   Starting ASR container..."
    docker start riva-speech 2>/dev/null || echo "   ⚠️ Please start ASR manually"
fi

# Start Brain (Nemotron 30B)
echo ""
echo "🧠 Starting Brain (Nemotron 30B)..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✓ Brain already running on port 8000"
else
    echo "   ⚠️ Brain not running. Please start with:"
    echo "      ./run_brain_quantized.sh"
fi

# Start llama.cpp TTS
echo ""
echo "🔊 Starting TTS (MOSS llama.cpp)..."
export PYTHONPATH=/home/phil/telephony-stack/moss-tts-src:$PYTHONPATH
export LD_LIBRARY_PATH=/home/telephony-stack/llama.cpp/build/lib:$LD_LIBRARY_PATH

/home/phil/telephony-stack-env/bin/python /home/phil/telephony-stack/tts_llama_server.py > /tmp/tts_llama.log 2>&1 &
TTS_PID=$!
echo $TTS_PID > /tmp/tts_llama.pid

# Wait for TTS to start
echo "   Waiting for TTS to initialize (this takes ~30s)..."
for i in {1..60}; do
    if curl -s http://localhost:5002/health > /dev/null 2>&1; then
        echo ""
        echo "   ✅ TTS server ready on port 5002"
        break
    fi
    sleep 1
    if [ $i -eq 60 ]; then
        echo ""
        echo "   ❌ TTS failed to start. Check /tmp/tts_llama.log"
        exit 1
    fi
done

# Check VRAM after TTS startup
echo ""
echo "📊 VRAM usage after TTS startup:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader | while read line; do
    echo "   GPU: $line"
done

# Start Telephony Bridge
echo ""
echo "📞 Starting Telephony Bridge..."
export TTS_BACKEND="llama"  # Signal to use llama.cpp endpoint
/home/phil/telephony-stack-env/bin/python telephony_bridge.py > /tmp/telephony.log 2>&1 &
BRIDGE_PID=$!
echo $BRIDGE_PID > /tmp/telephony.pid
sleep 2

# Summary
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    Stack Status                              ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  🧠 Brain (Nemotron 30B):  http://localhost:8000            ║"
echo "║  🎤 ASR (Nemotron Speech): grpc://localhost:50051           ║"
echo "║  🔊 TTS (MOSS llama.cpp):  http://localhost:5002            ║"
echo "║  📞 Telephony Bridge:      http://localhost:8080            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Log files:"
echo "   TTS:     tail -f /tmp/tts_llama.log"
echo "   Bridge:  tail -f /tmp/telephony.log"
echo ""
echo "To stop: ./stop_stack.sh"
echo ""

# Keep script running
wait
