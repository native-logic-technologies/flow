# Public Access Guide - CleanS2S Voice AI

## 🌐 Public Endpoints

Your CleanS2S telephony stack is now publicly accessible via Cloudflare Tunnel:

| Endpoint | URL | Protocol |
|----------|-----|----------|
| **WebSocket** | `wss://cleans2s.voiceflow.cloud/ws` | WebSocket |
| **Health Check** | `https://cleans2s.voiceflow.cloud/health` | HTTPS |
| **Info** | `https://cleans2s.voiceflow.cloud/` | HTTPS |

## 🚀 Quick Test

### 1. Browser Client
Open the web client in your browser:
```
https://cleans2s.voiceflow.cloud/web-client/index.html
```

Or serve it locally:
```bash
cd ~/telephony-stack/web-client
python3 -m http.server 8081
# Open http://localhost:8081
```

### 2. Command Line Test

Health check:
```bash
curl https://cleans2s.voiceflow.cloud/health
```

WebSocket test with wscat:
```bash
npm install -g wscat
wscat -c wss://cleans2s.voiceflow.cloud/ws
```

### 3. WebSocket Protocol

**Connect:**
```javascript
const ws = new WebSocket('wss://cleans2s.voiceflow.cloud/ws');
```

**Send Audio (8kHz, 16-bit PCM):**
```javascript
// Send Int16Array as binary
ws.send(audioBuffer);
```

**Receive Audio (24kHz, 16-bit PCM):**
```javascript
ws.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
        // Play synthesized speech
        const audioData = new Int16Array(event.data);
    }
};
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         PUBLIC INTERNET                          │
└──────────────────────┬──────────────────────────────────────────┘
                       │ WSS (WebSocket Secure)
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              CLOUDFLARE EDGE (DDoS Protection, SSL)              │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│           CLOUDFLARE TUNNEL (QUIC Protocol)                      │
│              tunnel: 12c14865-8b1b-4989-808d-fe0027dcc8d3       │
└──────────────────────┬──────────────────────────────────────────┘
                       │ ws://localhost:8080
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              DGX SPARK - ORCHESTRATOR (Port 8080)               │
│  ┌──────────────┐  ┌──────────┐  ┌────────┐  ┌─────────────┐   │
│  │ WebSocket    │  │ Silero   │  │        │  │             │   │
│  │ Server       │─▶│ VAD      │─▶│ Voxtral│─▶│  Nemotron   │   │
│  │ (Axum)       │  │ (ONNX)   │  │ ASR    │  │  LLM        │   │
│  └──────────────┘  └──────────┘  └────────┘  └─────────────┘   │
│         ▲                                            │          │
│         │                                            ▼          │
│  ┌──────┴─────────────────────────────────────────────────┐    │
│  │              EGRESS AUDIO (24kHz PCM)                   │    │
│  │              MOSS-TTS Voice Synthesis                    │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## 🔒 Security

- **SSL/TLS**: Automatic HTTPS via Cloudflare
- **DDoS Protection**: Cloudflare edge protection
- **No Direct Exposure**: Origin server not exposed to internet
- **Tunnel Authentication**: Cloudflare tunnel uses mTLS

## 📊 Performance

| Component | Latency |
|-----------|---------|
| Network (Global) | ~20-100ms |
| ASR (Voxtral) | ~40ms |
| LLM TTFT (Nemotron) | ~106ms |
| TTS (MOSS) | ~100ms |
| **Total E2E** | **~250-350ms** |

## 🔧 Management Commands

```bash
# View tunnel status
sudo systemctl status cloudflared-tunnel

# View logs
sudo journalctl -u cloudflared-tunnel -f

# Restart tunnel
sudo systemctl restart cloudflared-tunnel

# View all services
sudo systemctl status nemotron-llm voxtral-asr moss-tts telephony-orchestrator cloudflared-tunnel
```

## 🌐 Other Tunnel Endpoints

The same Cloudflare tunnel also exposes:

| Service | URL |
|---------|-----|
| Legacy Voice | `wss://voice.voiceflow.cloud` |
| Pipecat WebRTC | `https://pipecat.voiceflow.cloud` |
| LLM API | `https://llm.voiceflow.cloud` |
| Chat Interface | `https://chat.voiceflow.cloud` |

## 📝 Notes

- DNS: `cleans2s.voiceflow.cloud` → Cloudflare proxy
- Tunnel ID: `12c14865-8b1b-4989-808d-fe0027dcc8d3`
- Protocol: WebSocket over HTTPS (WSS)
- Audio Input: 8kHz, 16-bit PCM, mono
- Audio Output: 24kHz, 16-bit PCM, mono

## 🎉 You're Live!

Your CleanS2S voice AI is now publicly accessible. Share the URL:
**`https://cleans2s.voiceflow.cloud/web-client/index.html`**
