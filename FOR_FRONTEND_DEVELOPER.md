# For Frontend Developer - Secure JWT Integration

## ✅ Your Backend is Ready

**Token Endpoint:** `https://cleans2s.voiceflow.cloud/api/token`

## React/Vercel Integration

### 1. Environment Variables (Vercel Dashboard)

```
NEXT_PUBLIC_LIVEKIT_URL=wss://cleans2s.voiceflow.cloud
```

### 2. No API Route Needed!

Your frontend calls the DGX token server directly (CORS enabled).

### 3. Component Code

```tsx
'use client';

import { useEffect, useState } from 'react';
import { Room, RoomEvent } from 'livekit-client';

const LIVEKIT_URL = process.env.NEXT_PUBLIC_LIVEKIT_URL || 'wss://cleans2s.voiceflow.cloud';

export function VoiceChat() {
  const [connected, setConnected] = useState(false);
  const [room, setRoom] = useState<Room | null>(null);

  const connect = async () => {
    try {
      // 1. Fetch JWT token from DGX Spark
      const response = await fetch(`${LIVEKIT_URL.replace('wss:', 'https:')}/api/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          room: 'dgx-demo-room',
          // identity is optional, auto-generated if not provided
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to get token');
      }

      const { token, url, identity } = await response.json();
      console.log('Got token for:', identity);

      // 2. Connect to LiveKit
      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
      });

      await room.connect(url, token);
      await room.localParticipant.enableMicrophone();

      // 3. Listen for AI audio responses
      room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
        if (track.kind === 'audio') {
          const audio = new Audio();
          audio.autoplay = true;
          track.attach(audio);
          console.log('AI is speaking...');
        }
      });

      setRoom(room);
      setConnected(true);
      console.log('✅ Connected to DGX Spark!');

    } catch (error) {
      console.error('Connection failed:', error);
      alert('Failed to connect to voice AI');
    }
  };

  const disconnect = () => {
    room?.disconnect();
    setConnected(false);
    setRoom(null);
  };

  return (
    <div style={{ padding: '20px' }}>
      {!connected ? (
        <button 
          onClick={connect}
          style={{
            padding: '12px 24px',
            fontSize: '16px',
            backgroundColor: '#0070f3',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: 'pointer'
          }}
        >
          🎤 Connect to Voice AI
        </button>
      ) : (
        <div>
          <div style={{ 
            padding: '12px 24px',
            backgroundColor: '#10b981',
            color: 'white',
            borderRadius: '8px',
            marginBottom: '10px'
          }}>
            ✅ Connected - Speak now
          </div>
          <button 
            onClick={disconnect}
            style={{
              padding: '8px 16px',
              fontSize: '14px',
              backgroundColor: '#ef4444',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer'
            }}
          >
            Disconnect
          </button>
        </div>
      )}
    </div>
  );
}
```

### 4. Usage in Page

```tsx
// app/page.tsx or pages/index.tsx
import { VoiceChat } from './components/VoiceChat';

export default function Home() {
  return (
    <main style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
      <VoiceChat />
    </main>
  );
}
```

### 5. Install Dependencies

```bash
npm install livekit-client
```

## Testing Locally

```bash
npm run dev
# Open http://localhost:3000
```

## API Response Format

```typescript
interface TokenResponse {
  token: string;      // JWT token for LiveKit
  url: string;        // wss://cleans2s.voiceflow.cloud
  room: string;       // The room name
  identity: string;   // Unique user ID
}
```

## Security

- ✅ Token generated server-side (secret never exposed)
- ✅ CORS enabled for Vercel domains
- ✅ 6-hour token expiry
- ✅ Auto-generated unique identities

## Troubleshooting

### Connection Failed
1. Check DGX status: `curl https://cleans2s.voiceflow.cloud/health`
2. Verify token: `curl -X POST https://cleans2s.voiceflow.cloud/api/token -H "Content-Type: application/json" -d '{"room":"test"}'`

### CORS Errors
The DGX server allows:
- `https://*.vercel.app`
- `http://localhost:3000`
- `http://localhost:5173`

Add your custom domain to `token-server/token_api.py` if needed.

## Performance

Expected latency:
- Token generation: ~50ms
- WebSocket connection: ~100ms
- First audio response: ~640ms total
