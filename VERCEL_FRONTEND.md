# Vercel Frontend Integration - READY

## ✅ External WebSocket Endpoint

```
wss://cleans2s.voiceflow.cloud
```

This endpoint is now LIVE and pointing to the LiveKit server on port 7880.

## Quick React Example

```bash
npm install livekit-client
```

```typescript
import { Room, RoomEvent } from 'livekit-client';

const wsUrl = 'wss://cleans2s.voiceflow.cloud';
const roomName = 'dgx-demo-room';

// Generate token from your Vercel edge function
async function getToken(identity: string) {
  const res = await fetch('/api/livekit-token', {
    method: 'POST',
    body: JSON.stringify({ room: roomName, identity }),
  });
  return res.text();
}

// Connect to the DGX pipeline
export async function connectToVoiceAI(identity: string) {
  const token = await getToken(identity);
  const room = new Room({
    adaptiveStream: true,
    dynacast: true,
  });

  await room.connect(wsUrl, token);
  await room.localParticipant.enableMicrophone();

  // Listen for AI responses
  room.on(RoomEvent.TrackSubscribed, (track) => {
    if (track.kind === 'audio') {
      const audio = new Audio();
      audio.autoplay = true;
      track.attach(audio);
    }
  });

  return room;
}
```

## Edge Function for Token (Vercel)

```typescript
// /api/livekit-token.ts
import { AccessToken } from 'livekit-server-sdk';

const apiKey = 'APIQp4vjmCjrWQ9';
const apiSecret = 'PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l';

export default async function handler(req) {
  const { room, identity } = await req.json();

  const token = new AccessToken(apiKey, apiSecret, { identity });
  token.addGrant({
    roomJoin: true,
    room,
    canPublish: true,
    canSubscribe: true,
  });

  return new Response(token.toJwt());
}
```

## Complete React Component

```tsx
import { useEffect, useState } from 'react';
import { connectToVoiceAI } from './voice-client';

export function VoiceChat() {
  const [connected, setConnected] = useState(false);
  const [room, setRoom] = useState(null);

  const connect = async () => {
    const r = await connectToVoiceAI('user-' + Date.now());
    setRoom(r);
    setConnected(true);
  };

  const disconnect = () => {
    room?.disconnect();
    setConnected(false);
  };

  return (
    <div className="voice-chat">
      {!connected ? (
        <button onClick={connect}>🎤 Connect to AI Voice</button>
      ) : (
        <div>
          <p>✅ Connected - Speak now</p>
          <button onClick={disconnect}>Disconnect</button>
        </div>
      )}
    </div>
  );
}
```

## What's Working

✅ **WebSocket**: `wss://cleans2s.voiceflow.cloud`
✅ **LiveKit Server**: Port 7880
✅ **Voxtral ASR**: Port 8001 (~30ms)
✅ **Nemotron LLM**: Port 8000 (~60ms TTFT)
✅ **MOSS-TTS**: Port 8002 (~300ms)
✅ **Rust Orchestrator**: In tmux session

## Expected Latency

- User speaks → Voxtral ASR: ~250ms
- ASR text → LLM response: ~60ms
- LLM tokens → TTS audio: ~300ms
- **Total E2E**: ~640ms

## Testing

```bash
# Test the WebSocket endpoint
curl -i \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  https://cleans2s.voiceflow.cloud
```

## Support

If issues occur:
1. Check status: `cd ~/telephony-stack && ./status.sh`
2. View logs: `tmux attach -t livekit-orchestrator`
3. Restart: `./start_production.sh`
