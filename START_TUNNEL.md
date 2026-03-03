# Start Cloudflare Tunnel for flow.speak.ad

## Quick Start

### 1. Start the Cloudflare Tunnel

```bash
# Start the tunnel with the updated config
cloudflared tunnel --config ~/.cloudflared/config.yml run
```

### 2. In another terminal, start the local web server

```bash
cd ~/telephony-stack
python3 -m http.server 8080
```

### 3. Update your React app

Replace your `App.tsx` with the one in `~/telephony-stack/flow-speak-ad/App.tsx`

Or just change the URL:
```typescript
const url = "wss://flow.speak.ad";  // Instead of LiveKit Cloud
```

### 4. Deploy the React app

```bash
cd ~/flow-speak-ad  # Your React app directory
npm run build
npm run deploy      # Or however you deploy
```

## How It Works

1. **flow.speak.ad** → Cloudflare Tunnel → Local LiveKit (port 7880)
2. **Web client** served from `~/telephony-stack/web_client.html` at `flow.speak.ad/client`
3. **LiveKit room**: `dgx-spark-room`

## Testing

Once everything is running:

1. Open https://flow.speak.ad in your browser
2. Click "Start Call with Phil"
3. Speak into your microphone
4. You should hear the AI response within ~650ms

## Services Status

Make sure these are running:
- ✅ LLM (Nemotron) on port 8000
- ✅ ASR (Voxtral) on port 8001
- ✅ TTS (MOSS-TTS) on port 8002
- ✅ LiveKit on port 7880
- ✅ Orchestrator with Comma-Level Chunking
- ✅ cloudflared tunnel
- ✅ Python web server (for /client path)

## Troubleshooting

### "Failed to connect to DGX Spark"
- Check cloudflared is running
- Check LiveKit is running: `docker ps | grep livekit`
- Check tunnel status: `cloudflared tunnel info`

### "Authentication failed"
- The demo token uses client-side generation (insecure)
- For production, use a token server
- Or manually generate tokens with the LiveKit CLI

### No audio
- Check browser permissions
- Check LiveKit audio track is published
- Check orchestrator logs for errors
