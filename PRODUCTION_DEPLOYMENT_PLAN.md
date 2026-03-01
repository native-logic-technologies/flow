# Production Telephony Stack Deployment Plan

## Overview
Deploy the complete CleanS2S telephony stack (Nemotron LLM + Voxtral ASR + MOSS-TTS + Rust Orchestrator) as persistent systemd services, publicly accessible via LiveKit with authentication.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PUBLIC ACCESS LAYER                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  Cloudflare Tunnel / Reverse Proxy (HTTPS/WSS)                              │
│         │                                                                   │
│         ▼                                                                   │
│  LiveKit Server (Port 7880) - WebRTC SFU + Authentication                    │
│         │                                                                   │
│         ▼                                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                         ORCHESTRATION LAYER                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  Rust Telephony Orchestrator (Port 8080)                                     │
│    - WebSocket ingress from LiveKit                                          │
│    - Silero VAD (ONNX)                                                       │
│    - DeepFilterNet noise suppression                                         │
│         │                                                                   │
│    ┌────┴────┬──────────┬─────────────┐                                     │
│    ▼         ▼          ▼             ▼                                     │
│  Voxtral   Nemotron    MOSS-TTS    LiveKit                                  │
│  ASR       LLM         Voice       egress                                   │
│  (8001)    (8000)      (8002)      (WebRTC)                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Persistent Services (systemd)

### 1.1 Create systemd Service Files

Create services that auto-start on boot and restart on failure:

**File: `/etc/systemd/system/nemotron-llm.service`**
```ini
[Unit]
Description=Nemotron-3-Nano LLM (vLLM)
After=network.target
Wants=network.target

[Service]
Type=simple
User=phil
Group=phil
WorkingDirectory=/home/phil/telephony-stack
Environment="PATH=/home/phil/telephony-stack-env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="VLLM_WORKER_MULTIPROC_METHOD=spawn"
Environment="TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas"
Environment="HF_HOME=/tmp/hf_cache"
Environment="CUDA_HOME=/usr/local/cuda-13.0"
Environment="PYTHONUNBUFFERED=1"

ExecStart=/home/phil/telephony-stack-env/bin/python -m vllm.entrypoints.openai.api_server \
    --model /home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4 \
    --quantization modelopt_fp4 \
    --gpu-memory-utilization 0.2 \
    --max-model-len 32768 \
    --enforce-eager \
    --trust-remote-code \
    --chat-template /home/phil/telephony-stack/telephony_template.jinja \
    --port 8000

Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nemotron-llm

[Install]
WantedBy=multi-user.target
```

**File: `/etc/systemd/system/voxtral-asr.service`**
```ini
[Unit]
Description=Voxtral-Mini-4B-Realtime ASR (vLLM)
After=network.target nemotron-llm.service
Wants=network.target

[Service]
Type=simple
User=phil
Group=phil
WorkingDirectory=/home/phil/telephony-stack
Environment="PATH=/home/phil/telephony-stack-env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="VLLM_WORKER_MULTIPROC_METHOD=spawn"
Environment="TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas"
Environment="HF_HOME=/tmp/hf_cache"
Environment="CUDA_HOME=/usr/local/cuda-13.0"
Environment="PYTHONUNBUFFERED=1"

ExecStart=/home/phil/telephony-stack-env/bin/python -m vllm.entrypoints.openai.api_server \
    --model /home/phil/telephony-stack/models/asr/voxtral-mini-4b-realtime \
    --dtype bfloat16 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.1 \
    --enforce-eager \
    --trust-remote-code \
    --port 8001

Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=voxtral-asr

[Install]
WantedBy=multi-user.target
```

**File: `/etc/systemd/system/moss-tts.service`**
```ini
[Unit]
Description=MOSS-TTS-Realtime Voice Synthesis
After=network.target nemotron-llm.service
Wants=network.target

[Service]
Type=simple
User=phil
Group=phil
WorkingDirectory=/home/phil/telephony-stack
Environment="PATH=/home/phil/telephony-stack-env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="TRITON_PTXAS_PATH=/usr/local/cuda-13.0/bin/ptxas"
Environment="HF_HOME=/tmp/hf_cache"
Environment="PYTHONUNBUFFERED=1"
Environment="PYTHONPATH=/home/phil/telephony-stack/moss-tts-src:/home/phil/telephony-stack/moss-tts-src/moss_tts_realtime"

ExecStart=/home/phil/telephony-stack-env/bin/python /home/phil/telephony-stack/tts/moss_tts_fastapi_server.py

Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=moss-tts

[Install]
WantedBy=multi-user.target
```

**File: `/etc/systemd/system/telephony-orchestrator.service`**
```ini
[Unit]
Description=Rust Telephony Orchestrator (CleanS2S)
After=network.target nemotron-llm.service voxtral-asr.service moss-tts.service
Wants=network.target

[Service]
Type=simple
User=phil
Group=phil
WorkingDirectory=/home/phil/telephony-stack/orchestrator
Environment="RUST_LOG=info"
Environment="LLM_URL=http://localhost:8000/v1"
Environment="ASR_URL=http://localhost:8001/v1"
Environment="TTS_URL=http://localhost:8002/v1"
Environment="VAD_MODEL_PATH=/home/phil/telephony-stack/orchestrator/models/silero_vad.onnx"

ExecStart=/home/phil/telephony-stack/orchestrator/target/release/telephony-orchestrator

Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=telephony-orchestrator

[Install]
WantedBy=multi-user.target
```

### 1.2 Install and Enable Services

```bash
# Copy service files
sudo cp /home/phil/telephony-stack/systemd/*.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable services (start on boot)
sudo systemctl enable nemotron-llm.service
sudo systemctl enable voxtral-asr.service
sudo systemctl enable moss-tts.service
sudo systemctl enable telephony-orchestrator.service

# Start services
sudo systemctl start nemotron-llm.service
sudo systemctl start voxtral-asr.service
sudo systemctl start moss-tts.service
sudo systemctl start telephony-orchestrator.service

# Check status
sudo systemctl status nemotron-llm.service
sudo systemctl status telephony-orchestrator.service
```

### 1.3 View Logs

```bash
# Real-time logs
sudo journalctl -u nemotron-llm -f
sudo journalctl -u telephony-orchestrator -f

# All services
sudo journalctl -u nemotron-llm -u voxtral-asr -u moss-tts -u telephony-orchestrator -f
```

---

## Phase 2: LiveKit Deployment

### 2.1 Install LiveKit Server

```bash
# Download LiveKit server
curl -sSL https://get.livekit.io | bash

# Or manual install
wget https://github.com/livekit/livekit/releases/download/v1.8.0/livekit_1.8.0_linux_arm64.tar.gz
tar xzf livekit_1.8.0_linux_arm64.tar.gz
sudo mv livekit /usr/local/bin/
sudo mv livekit-cli /usr/local/bin/
```

### 2.2 Create LiveKit Configuration

**File: `/etc/livekit/livekit.yaml`**
```yaml
# LiveKit Server Configuration
port: 7880
bind_addresses:
  - "0.0.0.0"

# Logging
logging:
  level: info
  json: false

# WebRTC Configuration
rtc:
  udp_port: 7882
  tcp_port: 7881
  use_external_ip: true
  # DGX Spark is behind NAT, use STUN/TURN
  stun_servers:
    - "stun.l.google.com:19302"
    - "stun.cloudflare.com:3478"

# API Keys (generate strong keys for production)
keys:
  # Format: API_KEY: API_SECRET
  APIDKNNCLqYEtfx: supersecretkey_that_should_be_32_chars_long

# Webhook (optional - for call events)
webhook:
  url: "http://localhost:8080/webhook"
  api_key: APIDKNNCLqYEtfx

# Room Configuration
room:
  enabled_codecs:
    - mime: audio/opus
    - mime: audio/red
  empty_timeout: 300
  departure_timeout: 20

# TURN Server (for NAT traversal)
turn:
  enabled: true
  domain: turn.yourdomain.com
  cert_file: /etc/letsencrypt/live/yourdomain.com/fullchain.pem
  key_file: /etc/letsencrypt/live/yourdomain.com/privkey.pem
```

### 2.3 Create LiveKit systemd Service

**File: `/etc/systemd/system/livekit-server.service`**
```ini
[Unit]
Description=LiveKit WebRTC Server
After=network.target
Wants=network.target

[Service]
Type=simple
User=phil
Group=phil
ExecStart=/usr/local/bin/livekit --config /etc/livekit/livekit.yaml
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=livekit-server

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable livekit-server
sudo systemctl start livekit-server
```

---

## Phase 3: Public Access with SSL

### 3.1 Option A: Cloudflare Tunnel (Recommended)

Cloudflare Tunnel provides secure, authenticated access without exposing ports.

```bash
# Install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
sudo mv cloudflared-linux-arm64 /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared

# Authenticate (run once)
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create telephony-stack

# Get tunnel ID
cloudflared tunnel list

# Create config
mkdir -p ~/.cloudflared
```

**File: `~/.cloudflared/config.yml`**
```yaml
tunnel: YOUR_TUNNEL_ID
credentials-file: /home/phil/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  # LiveKit WebSocket
  - hostname: livekit.yourdomain.com
    service: ws://localhost:7880
    originRequest:
      noTLSVerify: true
  
  # LiveKit HTTP API
  - hostname: livekit-api.yourdomain.com
    service: http://localhost:7880
    originRequest:
      noTLSVerify: true
  
  # Orchestrator WebSocket (for direct testing)
  - hostname: orchestrator.yourdomain.com
    service: ws://localhost:8080
    originRequest:
      noTLSVerify: true
  
  # Default deny
  - service: http_status:404
```

**File: `/etc/systemd/system/cloudflared-tunnel.service`**
```ini
[Unit]
Description=Cloudflare Tunnel for Telephony Stack
After=network.target livekit-server.service
Wants=network.target

[Service]
Type=simple
User=phil
Group=phil
ExecStart=/usr/local/bin/cloudflared tunnel run telephony-stack
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable cloudflared-tunnel
sudo systemctl start cloudflared-tunnel
```

### 3.2 Option B: Caddy Reverse Proxy (Self-Hosted)

```bash
# Install Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

**File: `/etc/caddy/Caddyfile`**
```
# LiveKit WebSocket
livekit.yourdomain.com {
    reverse_proxy localhost:7880 {
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_up X-Forwarded-For {remote}
        header_up X-Forwarded-Proto {scheme}
    }
}

# Orchestrator WebSocket
orchestrator.yourdomain.com {
    reverse_proxy localhost:8080 {
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_up X-Forwarded-For {remote}
        header_up X-Forwarded-Proto {scheme}
    }
}
```

---

## Phase 4: Client Application

### 4.1 Web Client (LiveKit)

Create a simple web client that connects to LiveKit:

**File: `/home/phil/telephony-stack/web-client/index.html`**
```html
<!DOCTYPE html>
<html>
<head>
    <title>CleanS2S Voice AI</title>
    <script src="https://cdn.jsdelivr.net/npm/livekit-client@2.0.10/dist/livekit-client.umd.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        #status { padding: 20px; margin: 20px 0; border-radius: 8px; }
        .disconnected { background: #ffebee; color: #c62828; }
        .connecting { background: #fff3e0; color: #ef6c00; }
        .connected { background: #e8f5e9; color: #2e7d32; }
        button { padding: 15px 30px; font-size: 16px; cursor: pointer; margin: 5px; }
        #transcript { background: #f5f5f5; padding: 20px; border-radius: 8px; min-height: 200px; }
    </style>
</head>
<body>
    <h1>🎙️ CleanS2S Voice AI</h1>
    <div id="status" class="disconnected">Disconnected</div>
    
    <div>
        <button id="connectBtn" onclick="connect()">Connect</button>
        <button id="disconnectBtn" onclick="disconnect()" disabled>Disconnect</button>
    </div>
    
    <h3>Conversation:</h3>
    <div id="transcript"></div>

    <script>
        // LiveKit configuration
        const LIVEKIT_URL = 'wss://livekit.yourdomain.com';
        const API_KEY = 'APIDKNNCLqYEtfx';
        const API_SECRET = 'supersecretkey_that_should_be_32_chars_long';
        
        let room = null;
        let localTrack = null;
        
        async function connect() {
            updateStatus('connecting', 'Connecting...');
            
            // Get microphone access
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            // Connect to LiveKit
            room = new LivekitClient.Room({
                adaptiveStream: true,
                dynacast: true,
                publishDefaults: {
                    simulcast: false,
                    audioPreset: LivekitClient.AudioPresets.telephone
                }
            });
            
            // Handle events
            room.on('connected', () => {
                updateStatus('connected', 'Connected - Speak now!');
            });
            
            room.on('disconnected', () => {
                updateStatus('disconnected', 'Disconnected');
            });
            
            room.on('trackSubscribed', (track, publication, participant) => {
                if (track.kind === 'audio') {
                    const audioElement = new Audio();
                    audioElement.srcObject = new MediaStream([track.mediaStreamTrack]);
                    audioElement.play();
                }
            });
            
            // Generate token (in production, do this server-side)
            const token = await generateToken('user-' + Math.random().toString(36).substr(2, 9));
            
            // Connect
            await room.connect(LIVEKIT_URL, token);
            
            // Publish audio
            localTrack = await LivekitClient.LocalAudioTrack.createAudioTrack(
                'microphone',
                stream.getAudioTracks()[0]
            );
            await room.localParticipant.publishTrack(localTrack);
            
            document.getElementById('connectBtn').disabled = true;
            document.getElementById('disconnectBtn').disabled = false;
        }
        
        async function disconnect() {
            if (room) {
                await room.disconnect();
                room = null;
            }
            updateStatus('disconnected', 'Disconnected');
            document.getElementById('connectBtn').disabled = false;
            document.getElementById('disconnectBtn').disabled = true;
        }
        
        function updateStatus(state, message) {
            const status = document.getElementById('status');
            status.className = state;
            status.textContent = message;
        }
        
        // Simple token generation (DO THIS SERVER-SIDE IN PRODUCTION)
        async function generateToken(identity) {
            // In production, generate this on your server
            // For demo, you can use livekit-cli or a simple server endpoint
            const response = await fetch('/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ identity, room: 'telephony-test' })
            });
            return await response.text();
        }
    </script>
</body>
</html>
```

### 4.2 Token Server (Node.js/Python)

**File: `/home/phil/telephony-stack/web-client/token-server.py`**
```python
#!/usr/bin/env python3
"""Simple token server for LiveKit authentication"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import jwt
import time

app = Flask(__name__)
CORS(app)

# Configuration (move to environment variables in production)
LIVEKIT_API_KEY = "APIDKNNCLqYEtfx"
LIVEKIT_API_SECRET = "supersecretkey_that_should_be_32_chars_long"

def create_token(identity: str, room: str) -> str:
    """Create a LiveKit access token"""
    now = int(time.time())
    
    payload = {
        "iss": LIVEKIT_API_KEY,
        "sub": identity,
        "nbf": now,
        "exp": now + 3600,  # 1 hour validity
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        }
    }
    
    return jwt.encode(payload, LIVEKIT_API_SECRET, algorithm="HS256")

@app.route('/token', methods=['POST'])
def get_token():
    data = request.json
    identity = data.get('identity', 'anonymous')
    room = data.get('room', 'default-room')
    
    token = create_token(identity, room)
    return token

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
```

---

## Phase 5: Phone Integration (SIP)

### 5.1 Install LiveKit SIP

```bash
# Download LiveKit SIP
wget https://github.com/livekit/sip/releases/latest/download/livekit-sip_linux_arm64.tar.gz
tar xzf livekit-sip_linux-arm64.tar.gz
sudo mv livekit-sip /usr/local/bin/
```

**File: `/etc/livekit/sip.yaml`**
```yaml
# LiveKit SIP Configuration
api_key: APIDKNNCLqYEtfx
api_secret: supersecretkey_that_should_be_32_chars_long
ws_url: ws://localhost:7880

# SIP server configuration
sip:
  bind_port: 5060
  # Use a SIP trunk provider (Twilio, Telnyx, etc.)
  # Or configure for direct SIP
  
# Dispatch rules
room_templates:
  - name: "telephony-default"
    room_prefix: "phone-"
    auto_create: true
    
# Trunk configuration (example with Twilio)
trunks:
  - id: twilio-trunk
    kind: outbound
    address: trunk.twilio.com:5060
    transport: tcp
    username: "your_twilio_username"
    password: "your_twilio_password"
```

---

## Phase 6: Security & Monitoring

### 6.1 Firewall Configuration

```bash
# Allow only necessary ports
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH (change to your custom port if applicable)
sudo ufw allow 22/tcp

# LiveKit WebRTC
sudo ufw allow 7880/tcp
sudo ufw allow 7881/tcp
sudo ufw allow 7882/udp

# Internal services (localhost only)
# 8000, 8001, 8002, 8080 should NOT be exposed externally

sudo ufw enable
```

### 6.2 Monitoring (Prometheus + Grafana)

```yaml
# docker-compose.monitoring.yml
version: '3.8'
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
  
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana

volumes:
  grafana-data:
```

### 6.3 Health Check Script

**File: `/home/phil/telephony-stack/scripts/health-check.sh`**
```bash
#!/bin/bash
# Health check for all services

check_service() {
    local name=$1
    local url=$2
    
    if curl -s "$url" > /dev/null; then
        echo "✓ $name: OK"
        return 0
    else
        echo "✗ $name: FAIL"
        return 1
    fi
}

echo "=== CleanS2S Health Check ==="
echo "$(date)"
echo ""

check_service "Nemotron LLM" "http://localhost:8000/health"
check_service "Voxtral ASR" "http://localhost:8001/health"
check_service "MOSS-TTS" "http://localhost:8002/health"
check_service "LiveKit" "http://localhost:7880"

# Check GPU
echo ""
echo "=== GPU Status ==="
nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv,noheader
```

---

## Deployment Checklist

### Pre-deployment
- [ ] Generate strong API keys (not the example ones!)
- [ ] Configure domain names and DNS
- [ ] Set up SSL certificates (Cloudflare auto-handles this)
- [ ] Test all services locally
- [ ] Configure firewall rules

### Deployment
- [ ] Install systemd services
- [ ] Start core services (LLM, ASR, TTS)
- [ ] Verify all services healthy
- [ ] Install and configure LiveKit
- [ ] Set up Cloudflare tunnel or reverse proxy
- [ ] Deploy web client
- [ ] Test end-to-end conversation

### Post-deployment
- [ ] Set up monitoring (Prometheus/Grafana)
- [ ] Configure log rotation
- [ ] Set up alerting (Discord/Slack/PagerDuty)
- [ ] Document access URLs and credentials
- [ ] Create runbook for common issues

---

## Quick Start Commands

```bash
# 1. Start all services
sudo systemctl start nemotron-llm voxtral-asr moss-tts telephony-orchestrator livekit-server

# 2. Check status
sudo systemctl status nemotron-llm voxtral-asr moss-tts telephony-orchestrator livekit-server

# 3. View logs
sudo journalctl -u telephony-orchestrator -f

# 4. Restart after code changes
sudo systemctl restart telephony-orchestrator

# 5. Stop all
sudo systemctl stop nemotron-llm voxtral-asr moss-tts telephony-orchestrator livekit-server
```

---

## Next Steps

1. **Immediate**: Run the systemd setup commands in Phase 1
2. **Today**: Configure LiveKit and Cloudflare tunnel
3. **This week**: Set up monitoring and alerting
4. **Next**: Integrate with phone system (SIP trunk)

Ready to proceed with Phase 1 (systemd services)?
