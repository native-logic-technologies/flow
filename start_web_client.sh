#!/bin/bash
#
# Start a simple web server for the LiveKit S2S voice test client
#

echo "=============================================="
echo "LiveKit S2S Voice Test - Web Client"
echo "=============================================="
echo ""

# Check if Python is available
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "❌ Python not found"
    exit 1
fi

echo "✓ Using Python: $PYTHON"
echo ""

# Check services
echo "Checking services..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "  ✓ LLM (Nemotron) on port 8000"
else
    echo "  ✗ LLM not available"
fi

if curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo "  ✓ ASR (Voxtral) on port 8001"
else
    echo "  ✗ ASR not available"
fi

if curl -s http://localhost:8002/health > /dev/null 2>&1; then
    echo "  ✓ TTS (MOSS-TTS) on port 8002"
else
    echo "  ✗ TTS not available"
fi

if docker ps | grep -q livekit; then
    echo "  ✓ LiveKit on port 7880"
else
    echo "  ✗ LiveKit not available"
fi

echo ""
echo "Starting web server..."
echo "Open: http://localhost:8080/web_client.html"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Change to the directory
cd /home/phil/telephony-stack

# Start Python HTTP server on port 8080
$PYTHON -m http.server 8080
