#!/bin/bash
# Start the complete Qwen Omni Stack (Native vLLM)
# Qwen2.5-Omni (Ear) + Qwen3.5-9B (Brain) + MOSS-TTS (Voice)

set -e

cd /home/phil/telephony-stack

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║         🚀 Qwen Omni Stack - Full Deployment (Native)            ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║                                                                  ║"
echo "║  🎤 Ear:   Qwen2.5-Omni-7B    :8001  (Audio + Emotion)          ║"
echo "║  🧠 Brain: Qwen3.5-9B-NVFP4   :8000  (Reasoning + Vision)       ║"
echo "║  🎙️ Voice:  MOSS-TTS-Realtime  :8002  (Emotional Voice Clone)   ║"
echo "║  📞 Bridge: Qwen Omni          :8080  (Orchestrator)            ║"
echo "║                                                                  ║"
echo "║  Note: Using native vLLM (Docker lacks Qwen3.5/Omni support)    ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# Check VRAM
echo "📊 Initial VRAM:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "   %.1f GB / %.1f GB\n", $1/1024, $2/1024}'
echo ""

# Step 1: Start the Brain (Qwen3.5-9B)
echo "═══════════════════════════════════════════════════════════════════"
echo "STEP 1: Starting Brain (Qwen3.5-9B-NVFP4)..."
echo "═══════════════════════════════════════════════════════════════════"
chmod +x start_qwen_brain_native.sh
./start_qwen_brain_native.sh
sleep 2

echo ""
echo "📊 VRAM after Brain:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "   %.1f GB / %.1f GB\n", $1/1024, $2/1024}'

# Step 2: Start the Ear (Qwen2.5-Omni)
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "STEP 2: Starting Ear (Qwen2.5-Omni-7B)..."
echo "═══════════════════════════════════════════════════════════════════"
chmod +x start_qwen_ear_native.sh
./start_qwen_ear_native.sh
sleep 2

echo ""
echo "📊 VRAM after Ear:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "   %.1f GB / %.1f GB\n", $1/1024, $2/1024}'

# Step 3: Start the Voice (MOSS-TTS)
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "STEP 3: Starting Voice (MOSS-TTS-Realtime)..."
echo "═══════════════════════════════════════════════════════════════════"
chmod +x start_qwen_voice.sh
./start_qwen_voice.sh
sleep 2

echo ""
echo "📊 VRAM after Voice:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "   %.1f GB / %.1f GB\n", $1/1024, $2/1024}'

# Step 4: Start the Orchestrator
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "STEP 4: Starting Orchestrator..."
echo "═══════════════════════════════════════════════════════════════════"
pkill -f "qwen_omni_orchestrator" 2>/dev/null || true
sleep 1

/home/phil/telephony-stack-env/bin/python qwen_omni_orchestrator.py > /tmp/orchestrator.log 2>&1 &
ORCH_PID=$!
echo $ORCH_PID > /tmp/orchestrator.pid

echo "   Starting (PID: $ORCH_PID)..."
for i in {1..30}; do
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "   ✅ Orchestrator ready on port 8080"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo "   ❌ Orchestrator failed"
        exit 1
    fi
done

# Final Summary
echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                   ✅ Qwen Omni Stack Ready!                      ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║                                                                  ║"
echo "║  Service Health Checks:                                          ║"
echo "║    🧠 Brain:  curl http://localhost:8000/health                 ║"
echo "║    🎤 Ear:    curl http://localhost:8001/health                 ║"
echo "║    🎙️ Voice:  curl http://localhost:8002/voices                  ║"
echo "║    📞 Bridge: curl http://localhost:8080/health                 ║"
echo "║                                                                  ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║  Logs:                                                           ║"
echo "║    tail -f /tmp/brain.log        (Brain)                        ║"
echo "║    tail -f /tmp/ear.log          (Ear)                          ║"
echo "║    tail -f /tmp/tts.log          (Voice)                        ║"
echo "║    tail -f /tmp/orchestrator.log (Bridge)                       ║"
echo "║                                                                  ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║  VRAM Allocation:                                                ║"
echo "║    Brain: 35% (~45GB) - Logic & Reasoning                       ║"
echo "║    Ear:   40% (~51GB) - Audio Understanding                     ║"
echo "║    Voice: ~10GB       - Emotional Synthesis                     ║"
echo "║    Free:  ~22GB       - Headroom for KV cache                   ║"
echo "║                                                                  ║"
echo "╚══════════════════════════════════════════════════════════════════╝"

echo ""
echo "📊 Final VRAM Usage:"
nvidia-smi --query-gpu=memory.used,memory.total,memory.free --format=csv,noheader,nounits | awk '{printf "   Used: %.1f GB / Total: %.1f GB / Free: %.1f GB\n", $1/1024, $2/1024, $3/1024}'

echo ""
read -p "Press Enter to view logs (Ctrl+C to exit)..."
echo ""
echo "Showing orchestrator logs (Ctrl+C to exit)..."
tail -f /tmp/orchestrator.log
