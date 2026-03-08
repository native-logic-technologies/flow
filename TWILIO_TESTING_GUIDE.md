# 📞 Twilio Testing Guide - Dream Stack

This guide walks through testing the Dream Stack (Ear-Brain-Voice with emotional prosody) over real phone calls using Twilio.

---

## 🏗️ Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────────────────┐
│   Caller    │────▶│   Twilio    │────▶│  Dream Stack Orchestrator   │
│  (Phone)    │◄────│   (PSTN)    │◄────│  (Port 8080)                │
└─────────────┘     └─────────────┘     └─────────────────────────────┘
                                                   │
                          ┌────────────────────────┼────────────────────────┐
                          ▼                        ▼                        ▼
                   ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
                   │  Llama-Omni │          │  Nemotron   │          │  MOSS-TTS   │
                   │  (Ear)      │          │  (Brain)    │          │  (Voice)    │
                   │  Port 8001  │          │  Port 8000  │          │  Port 8002  │
                   └─────────────┘          └─────────────┘          └─────────────┘
```

---

## 📋 Prerequisites

### 1. Twilio Account
- Sign up at https://www.twilio.com/try-twilio
- Get a phone number (starts at $1/month)
- Note your **Account SID** and **Auth Token**

### 2. Public URL (Required for Twilio)
Twilio needs to reach your orchestrator. Options:

#### Option A: ngrok (Easiest for Testing)
```bash
# Install ngrok
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
tar xvzf ngrok-v3-stable-linux-arm64.tgz
sudo mv ngrok /usr/local/bin/

# Authenticate (get token from https://dashboard.ngrok.com/get-started/your-authtoken)
ngrok config add-authtoken YOUR_TOKEN

# Start tunnel to orchestrator
ngrok http 8080

# Copy the HTTPS URL (e.g., https://abc123.ngrok.io)
```

#### Option B: Cloudflare Tunnel (Persistent)
```bash
# Install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
sudo mv cloudflared /usr/local/bin/

# Login and create tunnel
cloudflared tunnel login
cloudflared tunnel create dream-stack
cd ~/.cloudflared

# Create config.yml
cat > config.yml << 'EOF'
tunnel: YOUR_TUNNEL_ID
credentials-file: /home/phil/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  - hostname: voice.yourdomain.com
    service: http://localhost:8080
  - service: http_status:404
EOF

# Run tunnel
cloudflared tunnel run dream-stack
```

### 3. Environment Setup

```bash
# Set your public URL
export PUBLIC_URL="https://abc123.ngrok.io"  # or your domain

# Set Twilio credentials (optional, for programmatic control)
export TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export TWILIO_AUTH_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

---

## 🚀 Deployment Steps

### Step 1: Start the Dream Stack

```bash
cd ~/telephony-stack

# Start all services
./start_dream_stack_llama_ear.sh

# Verify all services are running
curl http://localhost:8000/health  # Brain
curl http://localhost:8001/health  # Ear
curl http://localhost:8002/health  # Voice
```

### Step 2: Start the Orchestrator

```bash
# Terminal 1: Start the new emotional prosody orchestrator
python3 dream_orchestrator_v2.py

# Or use the hybrid orchestrator
python3 hybrid_orchestrator.py
```

### Step 3: Start ngrok Tunnel

```bash
# Terminal 2: Start tunnel
ngrok http 8080

# Copy the HTTPS forwarding URL
# Example: https://abc123-def456-gh.ngrok.io
```

### Step 4: Configure Twilio Webhook

1. Go to https://console.twilio.com/
2. Navigate to **Phone Numbers** → **Manage** → **Active numbers**
3. Click your phone number
4. Under **Voice & Fax**:
   - **A call comes in**: Webhook
   - **URL**: `https://your-ngrok-url/twilio/inbound`
   - **HTTP Method**: POST
5. Click **Save**

---

## 🧪 Testing

### Test 1: Basic Call

1. Call your Twilio number from your phone
2. Speak after the beep
3. The Dream Stack will:
   - Transcribe your speech (Ear)
   - Generate emotional response (Brain)
   - Synthesize with prosody (Voice)
   - Play back over the phone

### Test 2: Emotional Variation

Try saying things that trigger different emotions:

| You Say | Expected Emotion | Example Response |
|---------|------------------|------------------|
| "I just won the lottery!" | EXCITED | "That's incredible! I'm so excited for you!" |
| "My dog passed away" | EMPATHETIC | "I'm so sorry to hear that. That must be really hard." |
| "Can you help me with math?" | THINKING | "Let me think through this step by step..." |
| "There's a fire!" | URGENT | "Call 911 immediately! Get to safety now!" |

### Test 3: Latency Measurement

```bash
# In another terminal, watch the logs
tail -f /tmp/orchestrator.log | grep -E "Turn|latency|ms"
```

Expected output:
```
👂 Processing turn
🧠 Brain (145ms): [EMOTION: EXCITED] "That's amazing!"
   [0] excited: "That's amazing!"
   ⏱️  First audio at 195ms
🎙️  [0] excited: 50ms → 1.2s audio
   ✅ Turn complete
```

---

## 🔧 Troubleshooting

### Issue: "Application Error" on Call

**Check**: Orchestrator isn't running or ngrok URL is wrong

```bash
# Test orchestrator directly
curl http://localhost:8080/health

# Test through ngrok
curl https://your-ngrok-url/health
```

### Issue: No Audio Response

**Check**: Services down or WebSocket failing

```bash
# Check all services
ps aux | grep -E "vllm|llama-server|moss|orchestrator"

# Check logs
tail -50 /tmp/brain.log
tail -50 /tmp/llama_ear.log
tail -50 /tmp/moss.log
```

### Issue: High Latency (>500ms)

**Check**: GPU utilization and memory

```bash
nvidia-smi

# If VRAM full, restart services
pkill -f vllm
pkill -f llama-server
pkill -f moss
./start_dream_stack_llama_ear.sh
```

### Issue: Emotional Prosody Not Working

**Check**: Brain is outputting emotion tags

```bash
# Test Brain directly
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nemotron-3-nano-30b-nvfp4",
    "messages": [
      {"role": "system", "content": "Start response with [EMOTION: X]"},
      {"role": "user", "content": "I won the lottery!"}
    ],
    "max_tokens": 50
  }'

# Should output: [EMOTION: EXCITED] That's amazing!
```

---

## 📊 Monitoring

### Real-Time Metrics

Add to `dream_orchestrator_v2.py` to log metrics:

```python
@app.get("/metrics")
async def metrics():
    """Return latency metrics"""
    return {
        "calls_active": len(orchestrator.sessions),
        "avg_latency_ms": statistics.mean(orchestrator.latencies),
        "p95_latency_ms": sorted(orchestrator.latencies)[int(len*0.95)],
    }
```

### Log Analysis

```bash
# Extract latency statistics
grep "First audio" /tmp/orchestrator.log | awk '{print $4}' | sed 's/ms//' | sort -n

# Count errors
grep -c "ERROR" /tmp/orchestrator.log

# Real-time monitoring
watch -n 1 'curl -s http://localhost:8080/metrics'
```

---

## 🌍 Production Deployment

### Using a Permanent Domain

1. **Get a domain**: Use Cloudflare or any DNS provider
2. **Point DNS to your server** (if static IP) OR use Cloudflare Tunnel
3. **Configure HTTPS**: Use Cloudflare's automatic HTTPS
4. **Update Twilio webhook** to your domain

### Systemd Service

Create `/etc/systemd/system/dream-stack.service`:

```ini
[Unit]
Description=Dream Stack Orchestrator
After=network.target

[Service]
Type=simple
User=phil
WorkingDirectory=/home/phil/telephony-stack
Environment=PYTHONPATH=/home/phil/telephony-stack
Environment=PATH=/home/phil/telephony-stack-env/bin
ExecStart=/home/phil/telephony-stack-env/bin/python dream_orchestrator_v2.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl enable dream-stack
sudo systemctl start dream-stack
sudo systemctl status dream-stack
```

---

## 🎯 Expected Experience

### Caller Experience

1. **Dial number** → Hear ringing
2. **Connect** → Brief silence (~200ms)
3. **Speak** → "Hey, how's it going?"
4. **Wait** → ~200-400ms
5. **Hear response** → AI responds with appropriate emotional tone
6. **Continue conversation** → Natural back-and-forth

### Latency Breakdown

| Step | Time | Cumulative |
|------|------|------------|
| Caller speech ends | 0ms | 0ms |
| Ear (ASR) | ~500ms | 500ms |
| Brain (LLM TTFT) | ~100ms | 600ms |
| Voice (TTS TTFC) | ~50ms | 650ms |
| **First audio heard** | | **~650ms** |

### Emotional Quality

- **Excitement**: Higher pitch, faster tempo
- **Empathy**: Softer tone, slower pace
- **Urgency**: Direct, clear pronunciation
- **Calm**: Steady, measured delivery

---

## 🔐 Security Considerations

### ngrok (Development Only)
- Random URL changes on restart
- No authentication by default
- Use for testing only

### Production
- Use Cloudflare Tunnel with authentication
- Implement rate limiting
- Add webhook signature verification

```python
# Verify Twilio signature
from twilio.request_validator import RequestValidator

validator = RequestValidator(os.environ['TWILIO_AUTH_TOKEN'])
def validate_request(url, post_data, signature):
    return validator.validate(url, post_data, signature)
```

---

## 📞 Support

If issues persist:

1. Check all services: `curl http://localhost:800{0,1,2}/health`
2. Review logs: `tail -100 /tmp/*.log`
3. Test locally: `python3 test_conversational.py`
4. Check GPU: `nvidia-smi`

---

**Happy calling!** 📞🎉
