# Cloudflared Tunnel Setup for LiveKit

## Current Status

The tunnel `12c14865-8b1b-4989-808d-fe0027dcc8d3` is running and working:
- ✅ `cleans2s.voiceflow.cloud` → Port 8080 (old orchestrator)
- ⚠️ `livekit.voiceflow.cloud` → Port 7880 (needs DNS CNAME)

## Option 1: Add CNAME in Cloudflare DNS (Recommended)

Go to Cloudflare Dashboard → DNS → Add Record:

```
Type:    CNAME
Name:    livekit
Target:  12c14865-8b1b-4989-808d-fe0027dcc8d3.cfargotunnel.com
TTL:     Auto
Proxy:   Enabled (orange cloud)
```

This creates: `livekit.voiceflow.cloud`

Repeat for: `livekit.cleans2s.voiceflow.cloud`

## Option 2: Use Existing Endpoint with Port

If you can't modify DNS, use the existing tunnel endpoint with port forwarding:

```javascript
// Frontend connects to existing endpoint on different port
const room = new Room();
await room.connect('wss://cleans2s.voiceflow.cloud:7880', token);
```

**But this requires the port to be open in Cloudflare**, which isn't supported on free plans.

## Option 3: Path-Based WebSocket (Not Recommended for LiveKit)

LiveKit uses native WebRTC, not HTTP WebSocket for media. The signaling WebSocket needs to be on the root path.

## Working Solution for Vercel Frontend

Since cleans2s.voiceflow.cloud works, you have two options:

### Option A: Replace Port 8080 with LiveKit (Quick)

1. Stop the old orchestrator on port 8080:
   ```bash
   pkill -f "port 8080"
   ```

2. Update cloudflared config to point cleans2s.voiceflow.cloud to LiveKit:
   ```yaml
   - hostname: cleans2s.voiceflow.cloud
     service: ws://localhost:7880
   ```

3. Restart cloudflared

### Option B: Use Separate Hostname (Clean)

Add the CNAME record as shown in Option 1, then use:

```javascript
// Vercel frontend
const room = new Room();
await room.connect('wss://livekit.voiceflow.cloud', token);
```

## Current Config

```bash
# View current config
cat ~/.cloudflared/config.yml

# Restart tunnel if needed
pkill -f "cloudflared tunnel"
cloudflared tunnel --config ~/.cloudflared/config.yml run
```

## Testing

```bash
# Test local LiveKit
curl http://localhost:7880

# Test via tunnel (after DNS setup)
curl https://livekit.voiceflow.cloud
```

## Tunnel Commands

```bash
# List tunnels
cloudflared tunnel list

# View tunnel info
cloudflared tunnel info 12c14865-8b1b-4989-808d-fe0027dcc8d3

# Restart with new config
cloudflared tunnel --config ~/.cloudflared/config.yml run
```
