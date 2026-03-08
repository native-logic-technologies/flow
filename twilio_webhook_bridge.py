#!/usr/bin/env python3
"""
Twilio Webhook Bridge for Dream Stack
=====================================

This simple Flask server handles Twilio webhook requests and returns
TwiML that connects the call to the Rust orchestrator WebSocket.

Twilio Flow:
1. Call comes in → Twilio POSTs to /twilio/inbound
2. This server returns TwiML with <Stream> verb
3. Twilio connects WebSocket to wss://host/twilio/stream
4. Audio streams between caller and Dream Stack
"""

from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Say
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
WEBSOCKET_URL = os.environ.get('WEBSOCKET_URL', 'wss://cleans2s.voiceflow.cloud/twilio/stream')


@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return {'status': 'healthy', 'service': 'twilio-webhook-bridge'}


@app.route('/twilio/inbound', methods=['POST'])
def incoming_call():
    """
    Handle incoming Twilio call.
    
    Twilio sends:
    - CallSid: Unique call identifier
    - From: Caller phone number
    - To: Called Twilio number
    """
    call_sid = request.form.get('CallSid', 'unknown')
    from_number = request.form.get('From', 'unknown')
    to_number = request.form.get('To', 'unknown')
    
    logger.info(f"📞 Incoming call: {call_sid} from {from_number}")
    
    # Create TwiML response
    response = VoiceResponse()
    
    # Brief greeting (optional - can be removed for immediate connection)
    response.say("Hello! Connecting you now.", voice='Polly.Joanna')
    
    # Connect to Media Streams (WebSocket)
    connect = Connect()
    connect.stream(
        url=WEBSOCKET_URL,
        track='both_tracks'  # Send and receive audio
    )
    response.append(connect)
    
    # Fallback if stream fails
    response.say("Connection closed. Goodbye!", voice='Polly.Joanna')
    response.hangup()
    
    logger.info(f"✅ Returning TwiML for call {call_sid}")
    
    return Response(str(response), mimetype='text/xml')


@app.route('/twilio/stream', methods=['GET', 'POST'])
def stream_info():
    """
    Info endpoint for the stream.
    The actual WebSocket connection goes to the Rust orchestrator.
    """
    return {'status': 'WebSocket endpoint', 'url': WEBSOCKET_URL}


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8081))
    logger.info(f"🚀 Twilio Webhook Bridge starting on port {port}")
    logger.info(f"📞 Webhook URL: http://localhost:{port}/twilio/inbound")
    logger.info(f"🔗 WebSocket URL: {WEBSOCKET_URL}")
    
    # Run on 0.0.0.0 to accept connections from Cloudflare tunnel
    app.run(host='0.0.0.0', port=port, threaded=True)
