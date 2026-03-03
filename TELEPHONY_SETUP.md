# LiveKit Cloud + DGX Spark Telephony Setup

## Architecture
- **LiveKit Cloud**: Hosts SIP service, rooms, and signaling
- **DGX Spark (Your Server)**: Runs AI pipeline (Rust orchestrator + ASR/LLM/TTS)
- **Connection**: WebSocket from DGX to LiveKit Cloud

## Step 1: LiveKit Cloud Setup

1. Sign up: https://cloud.livekit.io
2. Create a new project
3. Go to **Settings** → **Project Settings**
4. Copy your:
   - **API Key** (starts with `API...`)
   - **API Secret**
   - **SIP URI** (e.g., `sip:abc123.sip.livekit.cloud`)

## Step 2: Twilio SIP Trunk

1. Twilio Console → **Elastic SIP Trunking** → **Create New Trunk**
2. **Termination Settings**:
   - SIP URI: Your LiveKit SIP URI (from step 1)
   - No authentication needed (IP whitelist instead)
3. **IP Whitelist**: Add LiveKit Cloud IPs (check LiveKit docs)
4. **Origination Settings**: Same SIP URI
5. Attach your Twilio phone number to this trunk

## Step 3: LiveKit Cloud Dispatch Rule

Go to **Telephony** → **Dispatch Rules** → **Create New**

```json
{
  "name": "phil-agent-dispatcher",
  "trunk_ids": [],
  "rule": {
    "dispatchRuleIndividual": {
      "roomPrefix": "call-",
      "pin": ""
    }
  }
}
```

This creates a unique room for each caller (e.g., `call-+1234567890`).

## Step 4: Update DGX Spark Orchestrator

Edit the orchestrator environment to connect to LiveKit Cloud:

```bash
export LIVEKIT_URL=wss://your-project.livekit.cloud
export LIVEKIT_API_KEY=APIxxxxxxxx
export LIVEKIT_API_SECRET=xxxxxxxx
export ROOM_NAME=call-  # Prefix for auto-join
```

## Step 5: Run Your Agent

The orchestrator will:
1. Connect to LiveKit Cloud via WebSocket
2. Auto-join any room starting with `call-`
3. Process audio from phone calls
4. Stream AI responses back

## How It Works

```
[Caller] → [Twilio] → [LiveKit Cloud SIP] → [LiveKit Room]
                                              ↓
                                    [WebSocket over internet]
                                              ↓
                                    [DGX Spark Rust Agent]
                                              ↓
                                    [Voxtral ASR → Nemotron LLM → MOSS TTS]
```

## Scaling

Each phone call = 1 LiveKit room + 1 DGX agent process

With 128GB VRAM:
- ~500 concurrent calls per DGX Spark
- Each call uses ~180MB VRAM (Nemotron-3-Nano + MOSS-TTS)

For 1000+ calls:
- Add a second DGX Spark
- Run multiple agent workers
- Load balance via LiveKit's dispatch rules
