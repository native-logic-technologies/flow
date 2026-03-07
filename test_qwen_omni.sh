#!/bin/bash
# Test the Qwen Omni Stack

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║         🧪 Testing Qwen Omni Stack                               ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# Test 1: Brain Health
echo "1️⃣  Testing Brain (Qwen3.5-9B-NVFP4)..."
BRAIN_HEALTH=$(curl -s http://localhost:8000/health 2>/dev/null | jq -r '.status' 2>/dev/null)
if [ "$BRAIN_HEALTH" == "healthy" ]; then
    echo "   ✅ Brain healthy"
    curl -s http://localhost:8000/health | jq -r '   Model: \(.model) | GPU: \(.gpu)'
else
    echo "   ❌ Brain not responding"
fi
echo ""

# Test 2: Brain Generation
echo "2️⃣  Testing Brain generation..."
BRAIN_RESPONSE=$(curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "/models/quantized/Qwen3.5-9B-NVFP4",
    "messages": [{"role": "user", "content": "Say hello"}],
    "max_tokens": 50
  }' 2>/dev/null | jq -r '.choices[0].message.content' 2>/dev/null)

if [ -n "$BRAIN_RESPONSE" ]; then
    echo "   ✅ Brain responding"
    echo "   Response: ${BRAIN_RESPONSE:0:60}..."
else
    echo "   ❌ Brain generation failed"
fi
echo ""

# Test 3: Ear Health
echo "3️⃣  Testing Ear (Qwen2.5-Omni-7B)..."
EAR_HEALTH=$(curl -s http://localhost:8001/health 2>/dev/null | jq -r '.status' 2>/dev/null)
if [ "$EAR_HEALTH" == "healthy" ]; then
    echo "   ✅ Ear healthy"
else
    echo "   ❌ Ear not responding"
fi
echo ""

# Test 4: Voice Health
echo "4️⃣  Testing Voice (MOSS-TTS-Realtime)..."
VOICE_HEALTH=$(curl -s http://localhost:8002/health 2>/dev/null | jq -r '.status' 2>/dev/null)
if [ "$VOICE_HEALTH" == "healthy" ]; then
    echo "   ✅ Voice healthy"
    curl -s http://localhost:8002/voices | jq -r '   Loaded voices: \(.loaded | join(", "))'
else
    echo "   ❌ Voice not responding"
fi
echo ""

# Test 5: TTS Generation
echo "5️⃣  Testing TTS generation..."
curl -s -X POST http://localhost:8002/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Hello, this is Phil speaking.",
    "voice": "neutral"
  }' -o /tmp/test_tts.pcm 2>/dev/null

if [ -f /tmp/test_tts.pcm ] && [ -s /tmp/test_tts.pcm ]; then
    FILESIZE=$(stat -c%s /tmp/test_tts.pcm)
    echo "   ✅ TTS generated audio (${FILESIZE} bytes)"
    echo "   Saved to: /tmp/test_tts.pcm"
else
    echo "   ❌ TTS generation failed"
fi
echo ""

# Test 6: Orchestrator Health
echo "6️⃣  Testing Orchestrator..."
ORCH_HEALTH=$(curl -s http://localhost:8080/health 2>/dev/null | jq -r '.status' 2>/dev/null)
if [ "$ORCH_HEALTH" == "healthy" ]; then
    echo "   ✅ Orchestrator healthy"
else
    echo "   ❌ Orchestrator not responding"
fi
echo ""

# Summary
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                      Test Summary                                ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

if [ "$BRAIN_HEALTH" == "healthy" ] && [ "$EAR_HEALTH" == "healthy" ] && [ "$VOICE_HEALTH" == "healthy" ] && [ "$ORCH_HEALTH" == "healthy" ]; then
    echo "✅ All services healthy! Stack is ready."
    echo ""
    echo "Next steps:"
    echo "  1. Configure Twilio webhook to: http://your-server:8080/twilio/inbound"
    echo "  2. Add voice samples to voices/{emotion}/reference.wav"
    echo "  3. Test with a phone call!"
else
    echo "⚠️  Some services are not responding. Check logs:"
    echo "     docker logs qwen-brain"
    echo "     docker logs qwen-ear"
    echo "     tail -f /tmp/tts.log"
fi
echo ""
