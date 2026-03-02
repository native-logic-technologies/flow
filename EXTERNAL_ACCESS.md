# External Access for Vercel Frontend

## Current Working Endpoint

✅ **WebSocket URL for LiveKit:**
```
wss://cleans2s.voiceflow.cloud
```

⚠️ **Port 8080** is currently serving the old orchestrator.

## Quick Fix Options

### Option 1: Update Frontend to Use Existing Endpoint (5 minutes)

Your Vercel frontend can connect to the existing working endpoint:

```javascript
const room = new Room();

// Use the existing tunnel endpoint
// Note: This currently goes to port 8080 (old orchestrator)
// We need to either:
// A) Change port 8080 to point to LiveKit (7880), OR
// B) Add a new CNAME for LiveKit

// For now, connect directly to DGX IP (if Vercel allows):
// const wsUrl = 'ws://<dgx-ip>:7880';  // Won't work with browser security

// Or use the tunnel with new CNAME:
const wsUrl = 'wss://livekit.cleans2s.voiceflow.cloud';  // Needs DNS setup
```

### Option 2: Switch Port 8080 to LiveKit (Immediate)

I can immediately switch the working endpoint to LiveKit:

```bash
# Stop old orchestrator
pkill -f "telephony.*8080" || true

# Update cloudflared to point 8080 to LiveKit
# (This will break the old /web-client)
```

Then your frontend uses:
```javascript
const wsUrl = 'wss://cleans2s.voiceflow.cloud';
```

### Option 3: Add New CNAME (Requires Cloudflare Access)

Add in Cloudflare DNS:
```
CNAME: livekit.cleans2s.voiceflow.cloud
Target: 12c14865-8b1b-4989-808d-fe0027dcc8d3.cfargotunnel.com
```

Then your frontend uses:
```javascript
const wsUrl = 'wss://livekit.cleans2s.voiceflow.cloud';
```

## Recommendation

**Option 2 is fastest** - switch cleans2s.voiceflow.cloud to point to LiveKit.

The old `/web-client` on port 8080 will be replaced, but the new LiveKit stack is better anyway.

Should I proceed with Option 2?
