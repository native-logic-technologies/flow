# Frontend Integration Guide (Vercel)

## Overview
Your Vercel frontend needs to connect to the DGX Spark pipeline via Cloudflared tunnels.

## External Endpoints

```
LiveKit WebSocket:  wss://livekit.voiceflow.cloud
HTTP API:           https://orchestrator.voiceflow.cloud
```

## React/Vue Integration

### 1. Install LiveKit Client SDK

```bash
npm install livekit-client
```

### 2. Connect to Room

```typescript
import { Room, RoomEvent } from 'livekit-client';

// Connect to the DGX pipeline
const room = new Room({
  adaptiveStream: true,
  dynacast: true,
  // Enable noise suppression for better ASR
  publishDefaults: {
    audioPreset: 'musicHighQuality',
    dtx: true,  // Reduce bandwidth when silent
  },
});

// Generate token (do this on your backend for security)
const token = await fetch('/api/livekit-token', {
  method: 'POST',
  body: JSON.stringify({ room: 'dgx-demo-room', identity: 'user-1' })
}).then(r => r.text());

// Connect
await room.connect('wss://livekit.voiceflow.cloud', token);
console.log('Connected to DGX Spark!');

// Enable microphone (audio goes to Voxtral ASR)
await room.localParticipant.enableMicrophone();

// Listen for AI audio responses
room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
  if (track.kind === 'audio') {
    // AI is speaking - play audio
    track.attach(document.createElement('audio'));
  }
});
```

### 3. Token Generation (Vercel Edge Function)

```typescript
// /api/livekit-token.ts
import { AccessToken } from 'livekit-server-sdk';

export default async function handler(req) {
  const { room, identity } = await req.json();
  
  const apiKey = 'APIQp4vjmCjrWQ9';
  const apiSecret = 'PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l';
  
  const token = new AccessToken(apiKey, apiSecret, {
    identity,
    name: identity,
  });
  
  token.addGrant({
    roomJoin: true,
    room,
    canPublish: true,
    canSubscribe: true,
  });
  
  return new Response(token.toJwt());
}
```

### 4. Complete React Component

```tsx
import { useEffect, useState } from 'react';
import { Room, RoomEvent } from 'livekit-client';

export function VoiceChat() {
  const [connected, setConnected] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const room = new Room();

  useEffect(() => {
    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === 'audio') {
        const audio = document.createElement('audio');
        audio.autoplay = true;
        track.attach(audio);
        setSpeaking(true);
        track.on('muted', () => setSpeaking(false));
      }
    });

    return () => room.disconnect();
  }, []);

  const connect = async () => {
    const token = await fetch('/api/livekit-token', {
      method: 'POST',
      body: JSON.stringify({ room: 'dgx-demo-room', identity: 'user-1' })
    }).then(r => r.text());

    await room.connect('wss://livekit.voiceflow.cloud', token);
    await room.localParticipant.enableMicrophone();
    setConnected(true);
  };

  return (
    <div>
      {!connected ? (
        <button onClick={connect}>Connect to AI Voice</button>
      ) : (
        <div>
          <p>🎤 Connected - Speak now</p>
          {speaking && <p>🔊 AI is speaking...</p>}
        </div>
      )}
    </div>
  );
}
```

## Testing Locally

```bash
# Terminal 1: Start pipeline (on DGX)
./start_production.sh

# Terminal 2: Run frontend locally
npm run dev
# Open http://localhost:3000
```

## Production Deployment

1. **Deploy to Vercel:**
   ```bash
   vercel --prod
   ```

2. **Add Environment Variables in Vercel Dashboard:**
   ```
   LIVEKIT_API_KEY=APIQp4vjmCjrWQ9
   LIVEKIT_API_SECRET=PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l
   LIVEKIT_URL=wss://livekit.voiceflow.cloud
   ```

3. **Verify CORS:**
   The Rust orchestrator accepts connections from any domain via LiveKit's WebRTC (which doesn't have CORS issues).

## Architecture Flow

```
User Browser (Vercel)
       │
       │ WebSocket (WSS)
       ▼
  Cloudflared Tunnel
       │
       ▼
  LiveKit Server:7880 ◄────┐
       │                    │
       │ WebRTC UDP         │
       ▼                    │
  Rust Orchestrator ────────┘
       │
       ├──► Voxtral ASR (8001)
       ├──► Nemotron LLM (8000)
       └──► MOSS-TTS (8002)
```

## Latency Expectations

| Stage | Latency |
|-------|---------|
| VAD | 250ms |
| Voxtral ASR | 30ms |
| LLM TTFT | 60ms |
| TTS | 300ms |
| **Total** | **~640ms** |

## Troubleshooting

### Connection Fails
```bash
# Check if pipeline is running
./status.sh

# Check LiveKit logs
docker logs livekit-server-livekit-1
```

### No Audio Output
- Check browser console for WebRTC errors
- Ensure microphone permissions are granted
- Verify `canSubscribe: true` in token

### High Latency
- Check GPU usage: `nvidia-smi`
- Ensure all services are on same machine (localhost)
- Verify Cloudflared is running: `tmux attach -t cloudflared`

## Security Notes

1. **Never expose API secrets in frontend code** - always use edge functions
2. **Room names** should be unique per session (e.g., UUID)
3. **Tokens expire** - implement refresh logic for long sessions

## Support

Pipeline status: `./status.sh`
View logs: `tmux attach -t livekit-orchestrator`
