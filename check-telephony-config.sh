#!/bin/bash
# Check telephony configuration

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           TELEPHONY CONFIGURATION CHECKER                     ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

SIP_URI="6aii08srz2e.sip.livekit.cloud"
WS_URL="wss://$SIP_URI"

echo "📞 SIP URI: sip:$SIP_URI"
echo "🌐 WebSocket: $WS_URL"
echo ""

# Check LiveKit Cloud credentials
echo "🔑 Checking LiveKit Cloud credentials..."
if [ -n "$LIVEKIT_CLOUD_API_KEY" ] && [ -n "$LIVEKIT_CLOUD_API_SECRET" ]; then
    echo "   ✅ LIVEKIT_CLOUD_API_KEY is set"
    echo "   ✅ LIVEKIT_CLOUD_API_SECRET is set"
    API_KEY="$LIVEKIT_CLOUD_API_KEY"
    API_SECRET="$LIVEKIT_CLOUD_API_SECRET"
elif [ -n "$LIVEKIT_API_KEY" ] && [ -n "$LIVEKIT_API_SECRET" ]; then
    echo "   ℹ️  Using LIVEKIT_API_KEY / LIVEKIT_API_SECRET"
    API_KEY="$LIVEKIT_API_KEY"
    API_SECRET="$LIVEKIT_API_SECRET"
else
    echo "   ❌ No LiveKit Cloud credentials found!"
    echo "      Get them from: https://cloud.livekit.io → Project Settings → API Keys"
    exit 1
fi

# Test connection to LiveKit Cloud
echo ""
echo "🌐 Testing LiveKit Cloud connection..."
if curl -s -o /dev/null -w "%{http_code}" "https://$SIP_URI" | grep -q "200\|401\|404"; then
    echo "   ✅ LiveKit Cloud is reachable"
else
    echo "   ❌ Cannot reach LiveKit Cloud"
fi

# Check AI services
echo ""
echo "🤖 Checking AI services on DGX Spark..."

# Check TTS
if nc -z localhost 8002 2>/dev/null; then
    echo "   ✅ MOSS-TTS (port 8002)"
else
    echo "   ❌ MOSS-TTS not responding (port 8002)"
fi

# Check ASR
if curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo "   ✅ Voxtral ASR (port 8001)"
else
    echo "   ⚠️  Voxtral ASR not responding (port 8001)"
fi

# Check LLM
if curl -s http://localhost:8000/v1/models > /dev/null 2>&1; then
    echo "   ✅ Nemotron LLM (port 8000)"
else
    echo "   ⚠️  Nemotron LLM not responding (port 8000)"
fi

# Check orchestrator
echo ""
echo "⚙️  Checking orchestrator..."
if [ -f "$HOME/telephony-stack/livekit_orchestrator/target/release/livekit_orchestrator" ]; then
    echo "   ✅ Orchestrator binary exists"
else
    echo "   ❌ Orchestrator not built!"
    echo "      cd ~/telephony-stack/livekit_orchestrator && cargo build --release"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Summary
if [ -n "$API_KEY" ] && [ -f "$HOME/telephony-stack/livekit_orchestrator/target/release/livekit_orchestrator" ]; then
    echo "✅ Configuration looks good!"
    echo ""
    echo "To start the telephony agent:"
    echo "   export LIVEKIT_CLOUD_API_KEY='$API_KEY'"
    echo "   export LIVEKIT_CLOUD_API_SECRET='$API_SECRET'"
    echo "   ./start-telephony.sh"
else
    echo "❌ Please fix the issues above before starting."
fi
