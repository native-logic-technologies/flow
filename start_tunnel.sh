#!/bin/bash
#
# Start Cloudflare Tunnel for flow.speak.ad
#

echo "=============================================="
echo "Starting Cloudflare Tunnel for flow.speak.ad"
echo "=============================================="
echo ""

# Check if cloudflared is installed
if ! command -v cloudflared &> /dev/null; then
    echo "❌ cloudflared not found"
    echo "Install from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation"
    exit 1
fi

echo "✓ cloudflared found: $(cloudflared --version)"
echo ""

# Check services
echo "Checking services..."
if curl -s http://localhost:7880 > /dev/null 2>&1; then
    echo "  ✓ LiveKit on port 7880"
else
    echo "  ✗ LiveKit not responding on port 7880"
    echo "    Start with: cd ~/telephony-stack/livekit-server && docker compose up -d"
    exit 1
fi

if pgrep -f livekit_orchestrator > /dev/null; then
    echo "  ✓ Orchestrator running"
else
    echo "  ✗ Orchestrator not running"
    echo "    Start with: cd ~/telephony-stack/livekit_orchestrator && ./target/release/livekit_orchestrator"
    exit 1
fi

echo ""
echo "Starting Cloudflare tunnel..."
echo "This will expose flow.speak.ad to the internet"
echo ""
echo "Tunnel config:"
echo "  - flow.speak.ad → ws://localhost:7880 (LiveKit)"
echo "  - flow.speak.ad/client → http://localhost:8080 (web client)"
echo ""
echo "Press Ctrl+C to stop"
echo ""

cloudflared tunnel --config ~/.cloudflared/config.yml run
