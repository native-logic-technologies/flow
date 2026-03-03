#!/bin/bash
#
# Setup Cloudflare Tunnel for Twilio Webhook
#

echo "=============================================="
echo "Twilio Integration Setup"
echo "=============================================="
echo ""

# Check if running from telephony-stack directory
if [ ! -f "twilio_server.py" ]; then
    echo "Error: Run this from ~/telephony-stack directory"
    exit 1
fi

echo "Step 1: Installing Flask and Twilio SDK..."
pip3 install flask twilio -q

echo ""
echo "Step 2: Adding Twilio routes to cloudflare tunnel..."

cat >> ~/.cloudflared/config.yml << 'EOF'

  # TWILIO WEBHOOK - For handling phone calls
  - hostname: twilio-bridge.voiceflow.cloud
    service: http://localhost:5000
    originRequest:
      noTLSVerify: true
EOF

echo "✓ Updated cloudflare config"
echo ""
echo "Step 3: Creating environment file..."

cat > ~/telephony-stack/.env.twilio << 'EOF'
# Twilio Configuration
# Get these from https://console.twilio.com

TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1234567890  # Your Twilio phone number

# LiveKit Configuration
LIVEKIT_URL=wss://cleans2s.voiceflow.cloud
LIVEKIT_ROOM=dgx-spark-room

# Server Configuration
PORT=5000
EOF

echo "✓ Created .env.twilio template"
echo ""
echo "Next steps:"
echo ""
echo "1. EDIT .env.twilio with your Twilio credentials:"
echo "   nano ~/telephony-stack/.env.twilio"
echo ""
echo "2. RESTART cloudflare tunnel:"
echo "   pkill cloudflared"
echo "   cloudflared tunnel --config ~/.cloudflared/config.yml run"
echo ""
echo "3. START the Twilio webhook server:"
echo "   source ~/telephony-stack/.env.twilio"
echo "   python3 ~/telephony-stack/twilio_server.py"
echo ""
echo "4. CONFIGURE Twilio webhook URL:"
echo "   Go to https://console.twilio.com"
echo "   Phone Numbers → Manage → Active Numbers"
echo "   Click your number"
echo "   Voice & Fax → A call comes in → Webhook"
echo "   URL: https://twilio-bridge.voiceflow.cloud/voice"
echo "   HTTP Method: POST"
echo ""
echo "5. TEST by calling your Twilio number!"
echo ""
