# LiveKit Token Server

Generates JWT tokens for secure frontend access to the DGX Spark LiveKit pipeline.

## Why This is Needed

LiveKit requires JWT tokens for authentication. This server:
- Generates tokens using your LiveKit API secret (kept server-side)
- Returns tokens to the frontend via CORS-enabled API
- Allows your Vercel frontend to connect securely without exposing secrets

## Endpoint

```
POST https://cleans2s.voiceflow.cloud/api/token
Content-Type: application/json

{
  "room": "dgx-demo-room",
  "identity": "user-123"  // optional, auto-generated if not provided
}
```

**Response:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "url": "wss://cleans2s.voiceflow.cloud",
  "room": "dgx-demo-room",
  "identity": "user-123"
}
```

## Frontend Usage (React/Vercel)

```typescript
// 1. Fetch token from DGX
const response = await fetch('https://cleans2s.voiceflow.cloud/api/token', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ room: 'dgx-demo-room' })
});

const { token, url } = await response.json();

// 2. Connect to LiveKit
import { Room } from 'livekit-client';
const room = new Room();
await room.connect(url, token);
await room.localParticipant.enableMicrophone();
```

## Security

- **CORS enabled** for Vercel domains (*.vercel.app)
- **No secrets exposed** to frontend
- **6-hour token expiry**
- **Auto-generated identities** if not provided

## Running

```bash
cd ~/telephony-stack/token-server
./start.sh
```

Or with tmux (persistent):
```bash
tmux new-session -d -s token-server -c ~/telephony-stack/token-server
./start.sh
```

## Testing

```bash
# Test token generation
curl -X POST https://cleans2s.voiceflow.cloud/api/token \
  -H "Content-Type: application/json" \
  -d '{"room": "test-room"}'

# Health check
curl https://cleans2s.voiceflow.cloud/health
```
