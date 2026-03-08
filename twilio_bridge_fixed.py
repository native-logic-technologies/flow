#!/usr/bin/env python3
"""Twilio ↔ Orchestrator Bridge"""

import asyncio
import websockets
import json
import base64
import audioop
import logging
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Connect, Say
from threading import Thread

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
ORCH_WS = "ws://127.0.0.1:8080/ws"
PORT = 8097
PUBLIC_WS = "wss://cleans2s.voiceflow.cloud/twilio/stream"

@app.route('/health')
def health():
    return {'status': 'ok'}

@app.route('/twilio/inbound', methods=['POST'])
def inbound():
    logger.info(f"📞 From: {request.form.get('From')}")
    r = VoiceResponse()
    r.say("Hello! Connecting you now.", voice='Polly.Joanna')
    c = Connect()
    c.stream(url=PUBLIC_WS, track='both_tracks')
    r.append(c)
    r.say("Goodbye!", voice='Polly.Joanna')
    r.hangup()
    return Response(str(r), mimetype='text/xml')

async def bridge(twilio_ws, path):
    logger.info(f"🔌 Connection: {path}")
    try:
        async with websockets.connect(ORCH_WS) as orch:
            logger.info("✅ Connected to orchestrator")
            async def t2o():
                async for m in twilio_ws:
                    try:
                        d = json.loads(m)
                        if d.get('event') == 'media':
                            mu = base64.b64decode(d['media']['payload'])
                            pcm = audioop.ulaw2lin(mu, 2)
                            await orch.send(pcm)
                        elif d.get('event') == 'start':
                            logger.info(f"▶️ Stream: {d['start']['streamSid']}")
                    except Exception as e:
                        logger.error(f"T2O: {e}")
            async def o2t():
                async for m in orch:
                    if isinstance(m, bytes):
                        mu = audioop.lin2ulaw(m)
                        pl = base64.b64encode(mu).decode()
                        await twilio_ws.send(json.dumps({'event':'media','media':{'payload':pl}}))
            await asyncio.gather(t2o(), o2t())
    except Exception as e:
        logger.error(f"❌ {e}")
    finally:
        logger.info("🔚 Disconnected")

async def ws_server():
    async with websockets.serve(bridge, '0.0.0.0', PORT):
        logger.info(f"🔊 WebSocket on port {PORT}")
        await asyncio.Future()

def run_flask():
    app.run(host='0.0.0.0', port=PORT, threaded=True, use_reloader=False)

async def main():
    logger.info(f"🚀 Bridge on port {PORT}")
    Thread(target=run_flask, daemon=True).start()
    await ws_server()

if __name__ == '__main__':
    asyncio.run(main())
