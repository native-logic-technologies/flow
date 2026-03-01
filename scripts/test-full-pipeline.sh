#!/bin/bash
# =============================================================================
# Test Full Voice AI Pipeline
# End-to-end test: Audio → ASR → LLM → TTS → Audio
# =============================================================================

set -e

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Flow - Full Pipeline Test                                         ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check if services are running
echo "Checking services..."
if ! curl -s http://localhost:8000/health > /dev/null; then
    echo "✗ Nemotron LLM not running on port 8000"
    exit 1
fi
echo "✓ Nemotron LLM (Port 8000)"

if ! curl -s http://localhost:8001/health > /dev/null; then
    echo "✗ Voxtral ASR not running on port 8001"
    exit 1
fi
echo "✓ Voxtral ASR (Port 8001)"

if ! curl -s http://localhost:8002/health > /dev/null; then
    echo "✗ MOSS-TTS not running on port 8002"
    exit 1
fi
echo "✓ MOSS-TTS (Port 8002)"

echo ""
echo "All services are running!"
echo ""

# Test 1: Direct LLM
echo "Test 1: Direct LLM Query"
echo "─────────────────────────────────────────────────────────────────────"
LLM_RESPONSE=$(curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant. Be concise."},
      {"role": "user", "content": "Say hello and introduce yourself briefly."}
    ],
    "max_tokens": 50,
    "temperature": 0.3
  }' 2>/dev/null)

# Try to extract content, show raw response if jq fails
echo "$LLM_RESPONSE" | jq -r '.choices[0].message.content' 2>/dev/null || echo "Raw response: $LLM_RESPONSE"
echo ""
echo ""

# Test 2: Direct TTS (with voice cloning)
echo "Test 2: Direct TTS Generation (with voice cloning)"
echo "─────────────────────────────────────────────────────────────────────"
echo "Generating speech with your voice..."
curl -s -X POST http://localhost:8002/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
    "input": "Hello! This is a test of the voice cloning system.",
    "response_format": "pcm"
  }' -o /tmp/test_output.pcm

if [ -f /tmp/test_output.pcm ] && [ -s /tmp/test_output.pcm ]; then
    echo "✓ TTS generated: $(ls -lh /tmp/test_output.pcm | awk '{print $5}')"
    echo "  To play: play -r 24000 -e signed -b 16 -c 1 /tmp/test_output.pcm"
else
    echo "✗ TTS failed - no output"
fi
echo ""

# Test 3: TTS with zero-shot voice cloning
echo "Test 3: TTS with Voice Cloning (if reference audio available)"
echo "─────────────────────────────────────────────────────────────────────"
VOICE_FILE="$HOME/telephony-stack/tts/phil-conversational-16k-5s.wav"

if [ -f "$VOICE_FILE" ]; then
    echo "Reference audio found: $(ls -lh $VOICE_FILE | awk '{print $5}')"
    
    # Encode to base64 and save to temp file (avoids "argument list too long")
    echo "Encoding reference audio..."
    base64 -w 0 "$VOICE_FILE" > /tmp/ref_audio.b64
    
    # Create JSON payload file
    echo "Creating request payload..."
    cat > /tmp/tts_request.json << 'JSONEOF'
{
  "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
  "input": "Hi, this is Phil speaking with my cloned voice.",
  "response_format": "pcm",
  "extra_body": {
    "reference_audio": "
JSONEOF
    cat /tmp/ref_audio.b64 >> /tmp/tts_request.json
    echo '"' >> /tmp/tts_request.json
    echo '  }' >> /tmp/tts_request.json
    echo '}' >> /tmp/tts_request.json
    
    echo "Sending request with voice cloning..."
    curl -s -X POST http://localhost:8002/v1/audio/speech \
      -H "Content-Type: application/json" \
      -d @/tmp/tts_request.json \
      -o /tmp/test_cloned_voice.pcm
    
    # Cleanup temp files
    rm -f /tmp/ref_audio.b64 /tmp/tts_request.json
    
    if [ -f /tmp/test_cloned_voice.pcm ] && [ -s /tmp/test_cloned_voice.pcm ]; then
        echo "✓ Cloned voice TTS generated: $(ls -lh /tmp/test_cloned_voice.pcm | awk '{print $5}')"
        echo "  To play: play -r 24000 -e signed -b 16 -c 1 /tmp/test_cloned_voice.pcm"
    else
        echo "✗ Cloned voice TTS failed - check /tmp/test_cloned_voice.pcm"
    fi
else
    echo "No reference audio found at $VOICE_FILE"
    echo "Skipping voice cloning test"
fi
echo ""

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Tests Complete!                                                   ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "To test full pipeline with orchestrator:"
echo "  1. Ensure orchestrator is running (Terminal 4)"
echo "  2. Send audio to ASR WebSocket: ws://localhost:8001/v1/realtime"
echo "  3. Orchestrator will handle: ASR → LLM → TTS"
echo ""
