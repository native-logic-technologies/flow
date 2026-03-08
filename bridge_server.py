#!/usr/bin/env python3
"""
Simple Twilio ↔ Orchestrator Bridge
===================================
"""

import asyncio
import websockets
import json
import base64
import audioop
import logging
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Connect, Say
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
ORCHESTRATOR_URL = "ws://localhost:8080/ws"


@app.route('/health')
def health():
    return {'status': 'healthy'}


@app.route('/twilio/inbound', methods=['POST'])
def inbound():
    logger.info(f"📞 Call from {request.form.get('From')}")
    resp = VoiceResponse()
    resp.say("Connecting...", voice='Polly.Joanna')
    connect = Connect()
    connect.stream(url='wss://cleans2s.voiceflow.cloud/twilio/stream', track='both_tracks')
    resp.append(connect)
    return Response(str(resp), mimetype='text/xml')


async def handle_twilio(twilio_ws, path):
    logger.info(f"🔌 New connection on {path}")
    try:
        orch_ws = await websockets.connect(ORCHESTRATOR_URL)
        logger.info("✅ Connected to orchestrator")
        
        async def t2o():
            async for msg in twilio_ws:
                try:
                    data = json.loads(msg)
                    if data.get('event') == 'media':
                        mulaw = base64.b64decode(data['media']['payload'])
                        pcm = audioop.ulaw2lin(mulaw, 2)
                        await orch_ws.send(pcm)
                    elif data.get('event') == 'start':
                        logger.info(f"▶️ Started: {data['start']['streamSid']}")
                except Exception as e:
                    logger.error(f"T2O error: {e}")
        
        async def o2t():
            async for msg in orch_ws:
                if isinstance(msg, bytes):
                    mulaw = audioop.lin2ulaw(msg)
                    payload = base64.b64encode(mulaw).decode()
                    await twilio_ws.send(json.dumps({'event': 'media', 'media': {'payload': payload}}))
        
        await asyncio.gather(t2o(), o2t())
    except Exception as e:
        logger.error(f"Bridge error: {e}")
    finally:
        logger.info("🔚 Connection closed")


def run_flask():
    app.run(host='0.0.0.0', port=8090, threaded=True)


async def main():
    logger.info("🚀 Bridge on port 8085")
    threading.Thread(target=run_flask, daemon=True).start()
    async with websockets.serve(handle_twilio, '0.0.0.0', 8090):
        logger.info("✅ WebSocket ready")
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
