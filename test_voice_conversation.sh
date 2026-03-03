#!/bin/bash
#
# Quick test script for voice conversation
# This provides multiple options for testing
#

echo "=============================================="
echo "Voice Conversation Test - Choose Option"
echo "=============================================="
echo ""

echo "1. Web Browser Client (Easiest)"
echo "   - Opens a web page where you can talk"
echo "   - Works on any device with a browser"
echo ""
echo "2. Python CLI Client"
echo "   - Command-line voice client"
echo "   - Requires: pip install livekit sounddevice"
echo ""
echo "3. Component Latency Test"
echo "   - Tests ASR->LLM->TTS without voice I/O"
echo "   - Measures actual latency numbers"
echo ""
echo "4. Full System Status"
echo "   - Check all services are running"
echo ""
read -p "Enter choice (1-4): " choice

case $choice in
    1)
        echo ""
        echo "Starting web server..."
        echo "Open: http://localhost:8080/web_client.html"
        echo ""
        cd /home/phil/telephony-stack
        python3 -m http.server 8080
        ;;
    2)
        echo ""
        echo "Checking dependencies..."
        python3 -c "import livekit, sounddevice" 2>/dev/null
        if [ $? -eq 0 ]; then
            echo "✓ Dependencies installed"
            python3 /home/phil/telephony-stack/test_livekit_client.py
        else
            echo "❌ Missing dependencies"
            echo "Install with: pip install livekit sounddevice numpy"
        fi
        ;;
    3)
        echo ""
        python3 /home/phil/telephony-stack/test_e2e_latency.py
        ;;
    4)
        echo ""
        echo "System Status:"
        echo "=============="
        
        # Check LLM
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo "  ✓ LLM (Nemotron) on port 8000"
        else
            echo "  ✗ LLM not responding"
        fi
        
        # Check ASR
        if curl -s http://localhost:8001/health > /dev/null 2>&1; then
            echo "  ✓ ASR (Voxtral) on port 8001"
        else
            echo "  ✗ ASR not responding"
        fi
        
        # Check TTS
        if curl -s http://localhost:8002/health > /dev/null 2>&1; then
            echo "  ✓ TTS (MOSS-TTS) on port 8002"
        else
            echo "  ✗ TTS not responding"
        fi
        
        # Check LiveKit
        if docker ps | grep -q livekit; then
            echo "  ✓ LiveKit on port 7880"
        else
            echo "  ✗ LiveKit not running"
        fi
        
        # Check Orchestrator
        if pgrep -f livekit_orchestrator > /dev/null; then
            echo "  ✓ Orchestrator running (PID: $(pgrep -f livekit_orchestrator | head -1))"
        else
            echo "  ✗ Orchestrator not running"
        fi
        
        echo ""
        echo "Configuration:"
        echo "  Room: dgx-spark-room"
        echo "  FLUSH_SIZE: 25 chars (Comma-Level)"
        echo "  prefill_text_len: 3 (TTS)"
        echo ""
        ;;
    *)
        echo "Invalid choice"
        ;;
esac
