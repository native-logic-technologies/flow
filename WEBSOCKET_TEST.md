# WebSocket Orchestrator - Testing Guide

## Overview
The orchestrator is now a standalone WebSocket server that accepts audio streams from clients and returns synthesized speech.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    YOUR DEVICE (Browser/Phone)                   │
│                         WebSocket Client                        │
└────────────────────┬────────────────────────────────────────────┘
                     │ WS Connection (ws://host:8080/ws)
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
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## WebSocket Protocol

### Connection
```javascript
const ws = new WebSocket('ws://localhost:8080/ws');
```

### Client → Server (Audio)
Send raw PCM audio (16-bit, 8kHz mono) as binary messages:
```javascript
// Get microphone stream
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
const audioContext = new AudioContext({ sampleRate: 8000 });
const source = audioContext.createMediaStreamSource(stream);
const processor = audioContext.createScriptProcessor(256, 1, 1);

processor.onaudioprocess = (e) => {
    const inputData = e.inputBuffer.getChannelData(0);
    // Convert Float32 to Int16
    const int16Data = new Int16Array(inputData.length);
    for (let i = 0; i < inputData.length; i++) {
        int16Data[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
    }
    // Send as binary
    ws.send(int16Data.buffer);
};
```

### Server → Client (Audio)
Receive synthesized speech as binary PCM (16-bit, 24kHz mono):
```javascript
ws.onmessage = (event) => {
    if (event.data instanceof Blob) {
        // Play audio
        const arrayBuffer = await event.data.arrayBuffer();
        const int16Data = new Int16Array(arrayBuffer);
        // Convert to Float32 and play...
    }
};
```

### Control Messages (JSON)
```javascript
// Ping
ws.send(JSON.stringify({ type: "ping" }));

// Interrupt (stop current TTS)
ws.send(JSON.stringify({ type: "interrupt" }));
```

## Quick Test

### Using wscat
```bash
# Install wscat
npm install -g wscat

# Connect
wscat -c ws://localhost:8080/ws

# Send ping
> {"type": "ping"}

# Send audio (you'd need to send binary)
# This won't work from wscat CLI but shows the format
```

### Using Python Test Script
```bash
# Create a simple test
python3 << 'EOF'
import asyncio
import websockets
import json

async def test():
    uri = "ws://localhost:8080/ws"
    async with websockets.connect(uri) as ws:
        # Send ping
        await ws.send(json.dumps({"type": "ping"}))
        print("Sent ping")
        
        # Send silence (zeros) - 1 second at 8kHz
        import struct
        silence = struct.pack('<' + 'h'*8000, *([0]*8000))
        await ws.send(silence)
        print("Sent 1 second of silence")
        
        # Wait for response
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"Received: {type(msg)} - {len(msg) if isinstance(msg, bytes) else msg}")
        except asyncio.TimeoutError:
            print("No response (expected - silence won't trigger ASR)")

asyncio.run(test())
EOF
```

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Info page |
| `/health` | GET | Health check + service status |
| `/ws` | WS | WebSocket for audio streaming |

## Status

All services are running:
```
✓ Nemotron LLM      : http://localhost:8000
✓ Voxtral ASR       : http://localhost:8001
✓ MOSS-TTS          : http://localhost:8002
✓ Rust Orchestrator : ws://localhost:8080
```

## Next Steps for Public Access

1. **Cloudflare Tunnel**: Expose WebSocket securely
2. **Web Client**: Build browser interface
3. **Authentication**: Add token-based auth

See `PRODUCTION_DEPLOYMENT_PLAN.md` for full details.
