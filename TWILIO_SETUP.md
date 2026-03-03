# Twilio + LiveKit Cloud Setup Guide

## Your LiveKit Cloud SIP URI
```
sip:6aii08srz2e.sip.livekit.cloud
```

## Step 1: Twilio Elastic SIP Trunk

1. **Twilio Console** → **Phone Numbers** → **Buy a number**
   - Choose a number with Voice capability
   - Remember this number (e.g., +1-555-123-4567)

2. **Twilio Console** → **Elastic SIP Trunking** → **Create New Trunk**
   - Name: `DGX-Spark-AI-Phil`

3. **Termination Settings** (Inbound calls to your DGX):
   - SIP URI: `sip:6aii08srz2e.sip.livekit.cloud`
   - Authentication: None (we'll use IP whitelist)
   - Click **Save**

4. **IP Access Control List**:
   - Click **Add ACL**
   - Add LiveKit Cloud IP ranges:
     ```
     34.102.0.0/16
     34.120.0.0/16
     34.149.0.0/16
     ```
   - (These are Google's IP ranges where LiveKit Cloud runs)

5. **Origination Settings** (Outbound calls from DGX):
   - SIP URI: `sip:6aii08srz2e.sip.livekit.cloud`
   - Priority: 1
   - Weight: 1
   - Click **Save**

6. **Attach Phone Number**:
   - Go to **Numbers** tab in your trunk
   - Click **Add Number**
   - Select your purchased number
   - Click **Add Selected**

## Step 2: LiveKit Cloud Dispatch Rule

1. **LiveKit Cloud Console** → **Telephony** → **Dispatch Rules**
2. Click **Create New Dispatch Rule**
3. Select **JSON Editor** tab
4. Paste:
```json
{
  "name": "phil-telephony-dispatch",
  "trunk_ids": [],
  "rule": {
    "dispatchRuleIndividual": {
      "roomPrefix": "call-",
      "pin": ""
    }
  }
}
```
5. Click **Create**

This means: When someone calls, create a room like `call-+15551234567`

## Step 3: Test the Call Flow

1. **Start your agent on DGX Spark**:
```bash
cd ~/telephony-stack
export LIVEKIT_URL=wss://6aii08srz2e.livekit.cloud
export LIVEKIT_API_KEY=APIQp4vjmCjrWQ9
export LIVEKIT_API_SECRET=PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l
./telephony-agent.sh call
```

2. **Call your Twilio number** from your phone

3. **What should happen**:
   - Phone rings
   - LiveKit Cloud answers via SIP
   - Room `call-+1555...` is created
   - Your DGX agent auto-joins the room
   - AI Phil speaks: "Hey there! I'm Phil..."
   - Full conversation begins

## Troubleshooting

### Call doesn't connect
- Check Twilio logs: Console → Monitor → Logs → SIP Trunking
- Verify IP whitelist includes LiveKit IPs
- Ensure dispatch rule is created

### Agent doesn't join
- Check DGX Spark can reach LiveKit Cloud:
  ```bash
  curl -I https://6aii08srz2e.livekit.cloud
  ```
- Verify API credentials
- Check orchestrator logs: `tail -f /tmp/orchestrator.log`

### No audio
- Check firewall on DGX: UDP ports 7882, 3478 must be open
- Verify ASR/LLM/TTS services are running on DGX
- Check LiveKit Cloud room has 2 participants

## Architecture

```
[Your Phone] 
      ↓
[Twilio PSTN] 
      ↓
[Twilio Elastic SIP Trunk] 
      ↓ (SIP)
[LiveKit Cloud: sip:6aii08srz2e.sip.livekit.cloud]
      ↓ (WebSocket)
[LiveKit Room: call-+15551234567]
      ↓ (WebSocket)
[DGX Spark: Rust Orchestrator]
      ↓
[ASR → LLM → TTS]
```

## Next: Outbound Calling

To make the AI call someone:
```bash
# Use LiveKit API to initiate outbound call
curl -X POST https://6aii08srz2e.livekit.cloud/twirml/Calls.json \
  -u "APIQp4vjmCjrWQ9:PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l" \
  -d "To=+15551234567" \
  -d "From=+15559876543" \
  -d "SipUrl=sip:6aii08srz2e.sip.livekit.cloud"
```

