#!/bin/bash
# Deploy MOSS-TTS-Realtime (The Voice) on Port 8002
# Role: Emotional Voice Synthesis with Zero-Shot Cloning
# Model: MOSS-TTS-Realtime

echo "🎙️ Starting MOSS-TTS-Realtime (The Voice) on Port 8002..."
echo ""

# Stop existing processes
pkill -f "tts_moss_realtime_server" 2>/dev/null || true
sleep 2

cd /home/phil/telephony-stack

# Set environment
export PYTHONPATH=/home/phil/telephony-stack:$PYTHONPATH
export HF_HOME=/tmp/hf_cache

# Start TTS server
/home/phil/telephony-stack-env/bin/python tts_moss_realtime_server.py > /tmp/tts.log 2>&1 &
TTS_PID=$!
echo $TTS_PID > /tmp/tts.pid

echo "   Server starting... (PID: $TTS_PID)"
echo ""

# Wait for health check
for i in {1..60}; do
    if curl -s http://localhost:8002/health > /dev/null 2>&1; then
        echo ""
        echo "   ✅ Voice ready on port 8002"
        echo ""
        echo "   Model: MOSS-TTS-Realtime"
        echo "   Output: 24kHz PCM"
        echo "   Emotions: neutral, empathetic, cheerful, thinking, urgent"
        echo ""
        break
    fi
    sleep 1
    if [ $i -eq 60 ]; then
        echo ""
        echo "   ❌ Voice failed to start"
        echo "   Check logs: tail -f /tmp/tts.log"
        exit 1
    fi
    if [ $i -eq 10 ]; then
        echo "   (Loading MOSS-TTS-Realtime model...)"
    fi
done

echo "🎙️ Voice server running."
echo "   Logs: tail -f /tmp/tts.log"
echo "   Test: curl http://localhost:8002/voices"
