#!/usr/bin/env python3
"""Twilio Media Streams ↔ Dream Stack Bridge"""

import asyncio
import websockets
import json
import base64
import audioop
import logging
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Say
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

ORCHESTRATOR_WS = "ws://localhost:8080/ws"
BRIDGE_PORT = 8083  # Changed to avoid conflict
PUBLIC_URL = f"wss://cleans2s.voiceflow.cloud/twilio/stream"


@app.route('/health')
def health():
    return {'status': 'healthy', 'service': 'twilio-bridge'}


@app.route('/twilio/inbound', methods=['POST'])
def twilio_inbound():
    call_sid = request.form.get('CallSid', 'unknown')
    from_num = request.form.get('From', 'unknown')
    logger.info(f"📞 Call {call_sid} from {from_num}")
    
    resp = VoiceResponse()
    resp.say("Hello! Connecting you now.", voice='Polly.Joanna')
    
    connect = Connect()
    connect.stream(url=PUBLIC_URL, track='both_tracks')
    resp.append(connect)
    
    resp.say("Goodbye!", voice='Polly.Joanna')
    resp.hangup()
    
    return Response(str(resp), mimetype='text/xml')


async def bridge_audio(twilio_ws, path):
    """Bridge Twilio Media Stream to Orchestrator."""
    logger.info(f"🔌 New connection: {path}")
    
    try:
        async with websockets.connect(ORCHESTRATOR_WS) as orch_ws:
            logger.info("✅ Connected to orchestrator")
            
            async def twilio_to_orch():
                async for msg in twilio_ws:
                    try:
                        data = json.loads(msg)
                        if data.get('event') == 'media':
                            mulaw = base64.b64decode(data['media']['payload'])
                            pcm = audioop.ulaw2lin(mulaw, 2)
                            await orch_ws.send(pcm)
                        elif data.get('event') == 'start':
                            logger.info(f"▶️  Stream started: {data['start']['streamSid']}")
                        elif data.get('event') == 'stop':
                            logger.info("⏹️  Stream stopped")
                            break
                    except Exception as e:
                        logger.error(f"T→O error: {e}")
            
            async def orch_to_twilio():
                async for msg in orch_ws:
                    if isinstance(msg, bytes):
                        mulaw = audioop.lin2ulaw(msg)
                        payload = base64.b64encode(mulaw).decode()
                        await twilio_ws.send(json.dumps({'event': 'media', 'media': {'payload': payload}}))
            
            await asyncio.gather(twilio_to_orch(), orch_to_twilio())
            
    except Exception as e:
        logger.error(f"Bridge error: {e}")
    finally:
        logger.info("🔚 Connection closed")


def run_flask():
    app.run(host='0.0.0.0', port=BRIDGE_PORT, threaded=True)


async def main():
    logger.info(f"🚀 Bridge starting on port {BRIDGE_PORT}")
    logger.info(f"📞 Webhook: http://localhost:{BRIDGE_PORT}/twilio/inbound")
    logger.info(f"🔌 WebSocket: ws://localhost:{BRIDGE_PORT}/twilio/stream")
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start WebSocket server
    async with websockets.serve(bridge_audio, '0.0.0.0', BRIDGE_PORT):
        logger.info("✅ Ready for connections")
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
