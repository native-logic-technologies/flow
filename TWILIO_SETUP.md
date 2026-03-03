# Twilio Integration Guide for DGX Spark Voice AI

This guide connects your Twilio phone number to your LiveKit S2S pipeline running on DGX Spark.

## Architecture

```
Phone Call → Twilio → LiveKit SIP → Orchestrator → LLM → TTS → Back to Phone
```

## Option 1: LiveKit SIP (Recommended)

LiveKit has native SIP support for connecting to phone networks via Twilio.

### Step 1: Configure LiveKit for SIP

```bash
# Edit LiveKit config
cd ~/telephony-stack/livekit-server
nano livekit.yaml
```

Add SIP configuration:
```yaml
# Add to livekit.yaml
sip:
  enabled: true
  # Local UDP port range for SIP media
  udp_port_range_start: 10000
  udp_port_range_end: 20000
  
  # External IP for SIP (your server's public IP)
  external_ip: YOUR_SERVER_PUBLIC_IP
```

### Step 2: Set Up Twilio SIP Trunk

1. **Log into Twilio Console**: https://console.twilio.com

2. **Create a SIP Trunk**:
   - Go to "Elastic SIP Trunking" → "Trunks" → "Create new Trunk"
   - Name: "DGX-Spark-Voice-AI"
   
3. **Configure Origination (Incoming calls)**:
   - Origination SIP URI: `sip:cleans2s.voiceflow.cloud:5060`
   - Or use your server's IP: `sip:YOUR_IP:5060`
   - Authentication: Create username/password
   
4. **Configure Termination (Outgoing calls)**:
   - Termination SIP URI: `sip:cleans2s.voiceflow.cloud:5060`
   - Authentication: Same credentials

5. **Assign Phone Number**:
   - Buy a Twilio phone number
   - Attach it to your SIP Trunk

### Step 3: Create LiveKit SIP Participant

Your orchestrator needs to handle SIP participants joining the room:

```python
# Add to your orchestrator or create a sip_handler.py
import livekit

async def handle_sip_call(room_name: str, from_number: str):
    """Handle incoming SIP call from Twilio"""
    
    # Join the room as an agent
    room = await livekit.Room.connect(
        "wss://cleans2s.voiceflow.cloud",
        room_name,
    )
    
    # The SIP participant will automatically join as a participant
    # Your orchestrator handles them like any other participant
    
    return room
```

## Option 2: Twilio Media Streams (WebSocket)

For more control, use Twilio's Media Streams to stream audio via WebSocket.

### Step 1: Create TwiML App

1. **Create TwiML App** in Twilio Console:
   - Go to "Phone Numbers" → "Manage" → "TwiML Apps" → "Create new"
   - Friendly Name: "DGX Voice AI"
   
2. **Voice Request URL**: 
   ```
   https://cleans2s.voiceflow.cloud/twilio-webhook
   ```

### Step 2: Create Webhook Handler

```python
# twilio_webhook.py
from flask import Flask, request, Response
import xml.etree.ElementTree as ET

app = Flask(__name__)

@app.route('/twilio-webhook', methods=['POST'])
def incoming_call():
    """Handle incoming Twilio call"""
    
    call_sid = request.form.get('CallSid')
    from_number = request.form.get('From')
    
    # Generate TwiML response with Media Streams
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Connect>
            <Stream url="wss://cleans2s.voiceflow.cloud/twilio-stream" />
        </Connect>
    </Response>"""
    
    return Response(twiml, mimetype='text/xml')

@app.route('/twilio-stream', methods=['GET'])
def stream_websocket():
    """WebSocket handler for media streams"""
    # This would upgrade to WebSocket and handle audio
    pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

### Step 3: Connect Media Stream to LiveKit

Bridge Twilio's WebSocket to LiveKit:

```python
# twilio_livekit_bridge.py
import asyncio
import websockets
import livekit

async def bridge_twilio_to_livekit(twilio_ws, livekit_room):
    """Bridge audio between Twilio and LiveKit"""
    
    async for message in twilio_ws:
        data = json.loads(message)
        
        if data['event'] == 'media':
            # Get audio from Twilio (mulaw 8khz)
            audio_payload = data['media']['payload']
            
            # Convert and send to LiveKit
            # ... conversion logic ...
            
        elif data['event'] == 'start':
            print(f"Call started: {data['start']['callSid']}")
            
        elif data['event'] == 'stop':
            print(f"Call ended: {data['stop']['callSid']}")
            break
```

## Option 3: Simple HTTP Webhook (Fastest Setup)

Use Twilio's `<Dial>` to connect directly to your server.

### Step 1: Create Simple Server

```python
# twilio_simple.py
from flask import Flask, request, Response

app = Flask(__name__)

@app.route('/voice', methods=['POST'])
def voice():
    """Handle incoming call"""
    
    # Return TwiML to stream to your WebSocket endpoint
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>Connecting you to DGX Spark Voice AI.</Say>
        <Connect>
            <Stream url="wss://cleans2s.voiceflow.cloud/ws" />
        </Connect>
    </Response>"""
    
    return Response(twiml, mimetype='text/xml')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

### Step 2: Configure Twilio

1. **Buy a Twilio phone number**
2. **Configure webhook**:
   - Voice & Fax → A call comes in → Webhook
   - URL: `https://cleans2s.voiceflow.cloud:5000/voice`
   - HTTP Method: POST

### Step 3: Expose Your Server

```bash
# Option A: Use cloudflare tunnel to expose port 5000
cloudflared tunnel route dns 12c14865-8b1b-4989-808d-fe0027dcc8d3 twilio-bridge.voiceflow.cloud

# Then update config.yml with:
# - hostname: twilio-bridge.voiceflow.cloud
#   service: http://localhost:5000
```

## Quick Start (Recommended Path)

### 1. Get Twilio Credentials
- Sign up: https://www.twilio.com/try-twilio
- Buy a phone number ($1/month)
- Get Account SID and Auth Token

### 2. Configure Phone Number Webhook
```
Voice Configuration:
  When a call comes in: Webhook
  URL: https://cleans2s.voiceflow.cloud/twilio-voice
  HTTP Method: POST
```

### 3. Add Webhook Handler to Your Stack

```bash
# Create the webhook server
cd ~/telephony-stack
cat > twilio_server.py << 'EOF'
from flask import Flask, request, Response
import requests

app = Flask(__name__)

# Your LiveKit room
ROOM_NAME = "dgx-spark-room"
LIVEKIT_URL = "wss://cleans2s.voiceflow.cloud"

@app.route('/twilio-voice', methods=['POST'])
def handle_call():
    call_sid = request.form.get('CallSid')
    from_number = request.form.get('From')
    
    print(f"Incoming call from {from_number}, SID: {call_sid}")
    
    # Option A: Connect via SIP (if LiveKit SIP is configured)
    # Option B: Use Media Streams
    
    # For now, return simple response
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Hello! You've reached DGX Spark Voice AI. This feature is coming soon.</Say>
    <Pause length="1"/>
    <Say>For now, please visit cleans2s dot voiceflow dot cloud to try our web interface.</Say>
    <Hangup/>
</Response>"""
    
    return Response(twiml, mimetype='text/xml')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
EOF
```

### 4. Expose via Cloudflare Tunnel

Add to `~/.cloudflared/config.yml`:
```yaml
- hostname: twilio-bridge.voiceflow.cloud
  service: http://localhost:5000
  originRequest:
    noTLSVerify: true
```

### 5. Run Everything

```bash
# Terminal 1: Start LiveKit services
# (Already running)

# Terminal 2: Start Twilio webhook server
cd ~/telephony-stack
python3 twilio_server.py

# Terminal 3: Cloudflare tunnel (already running)
# cloudflared tunnel run
```

## Testing

1. **Call your Twilio number** from your phone
2. **Check logs** in twilio_server.py
3. **Verify** the call connects

## Next Steps

To fully integrate:
1. Set up LiveKit SIP or Media Streams bridge
2. Connect Twilio audio stream to your orchestrator
3. Handle bidirectional audio (caller voice → ASR → LLM → TTS → caller ear)

## Resources

- Twilio SIP Trunking: https://www.twilio.com/sip-trunking
- Twilio Media Streams: https://www.twilio.com/docs/voice/media-streams
- LiveKit SIP: https://docs.livekit.io/sip/
- LiveKit Twilio Integration: https://github.com/livekit/twilio-media-streams
