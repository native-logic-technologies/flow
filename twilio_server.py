#!/usr/bin/env python3
"""
Twilio Webhook Server for DGX Spark Voice AI
============================================

This server handles incoming Twilio calls and can:
1. Bridge them to LiveKit (SIP or Media Streams)
2. Handle basic voice responses
3. Log call information

Setup:
1. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment variables
2. Run this server: python3 twilio_server.py
3. Configure Twilio webhook URL to point to your tunnel
4. Call your Twilio number!
"""

from flask import Flask, request, Response, jsonify
import os
import json
import logging
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Say, Hangup

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
LIVEKIT_URL = os.environ.get('LIVEKIT_URL', 'wss://cleans2s.voiceflow.cloud')
LIVEKIT_ROOM = os.environ.get('LIVEKIT_ROOM', 'dgx-spark-room')
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')

# Initialize Twilio client if credentials available
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'twilio-webhook',
        'livekit_url': LIVEKIT_URL,
        'room': LIVEKIT_ROOM
    })


@app.route('/voice', methods=['POST'])
def incoming_call():
    """
    Handle incoming Twilio voice call
    
    This is the main webhook endpoint that Twilio calls when someone
    dials your Twilio phone number.
    """
    call_sid = request.form.get('CallSid', 'unknown')
    from_number = request.form.get('From', 'unknown')
    to_number = request.form.get('To', 'unknown')
    
    logger.info(f"Incoming call: {call_sid} from {from_number} to {to_number}")
    
    # Create TwiML response
    response = VoiceResponse()
    
    # Greeting
    response.say(
        "Hello! You've reached DGX Spark Voice AI.",
        voice='Polly.Joanna'
    )
    
    # Option 1: Simple bridge to LiveKit via Media Streams
    # This streams audio to/from your LiveKit orchestrator
    connect = Connect()
    connect.stream(
        url=f'{LIVEKIT_URL.replace("wss://", "wss://")}/twilio-media',
        track='both_tracks'
    )
    response.append(connect)
    
    # Fallback if stream fails
    response.say(
        "I'm sorry, but I'm having trouble connecting you right now. "
        "Please try again later or visit cleans2s dot voiceflow dot cloud.",
        voice='Polly.Joanna'
    )
    response.hangup()
    
    return Response(str(response), mimetype='text/xml')


@app.route('/twilio-media', methods=['GET', 'POST'])
def handle_media_stream():
    """
    Handle Twilio Media Stream WebSocket upgrade
    
    Twilio will try to upgrade this HTTP connection to WebSocket
    for bidirectional audio streaming.
    """
    # This is where you'd handle the WebSocket connection
    # For now, return 426 Upgrade Required
    logger.info("Media stream connection attempted")
    
    # In production, this would upgrade to WebSocket
    # and bridge to LiveKit
    
    return Response(
        "WebSocket upgrade required",
        status=426,
        mimetype='text/plain'
    )


@app.route('/status', methods=['POST'])
def call_status():
    """
    Handle Twilio call status callbacks
    
    Twilio sends status updates as the call progresses
    """
    call_sid = request.form.get('CallSid')
    call_status = request.form.get('CallStatus')
    call_duration = request.form.get('CallDuration', 0)
    
    logger.info(f"Call {call_sid} status: {call_status}, duration: {call_duration}s")
    
    return '', 204


@app.route('/make-call', methods=['POST'])
def make_outbound_call():
    """
    Make an outbound call via Twilio
    
    POST /make-call
    {
        "to": "+1234567890",
        "message": "Optional custom message"
    }
    """
    if not twilio_client:
        return jsonify({'error': 'Twilio not configured'}), 500
    
    data = request.get_json()
    to_number = data.get('to')
    message = data.get('message', 'Hello from DGX Spark Voice AI!')
    
    if not to_number:
        return jsonify({'error': 'Missing "to" number'}), 400
    
    try:
        # Get your Twilio phone number
        # In production, use a specific number from your account
        from_number = os.environ.get('TWILIO_PHONE_NUMBER')
        
        if not from_number:
            return jsonify({'error': 'TWILIO_PHONE_NUMBER not configured'}), 500
        
        # Create the call
        call = twilio_client.calls.create(
            to=to_number,
            from_=from_number,
            url='https://cleans2s.voiceflow.cloud/voice',
            status_callback='https://cleans2s.voiceflow.cloud/status',
            status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
            status_callback_method='POST'
        )
        
        logger.info(f"Outbound call created: {call.sid}")
        
        return jsonify({
            'success': True,
            'call_sid': call.sid,
            'status': call.status
        })
        
    except Exception as e:
        logger.error(f"Failed to make call: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/sip', methods=['POST'])
def sip_incoming():
    """
    Handle incoming SIP calls
    
    For SIP trunking integration with Twilio
    """
    call_sid = request.form.get('CallSid', 'unknown')
    from_number = request.form.get('From', 'unknown')
    
    logger.info(f"Incoming SIP call: {call_sid} from {from_number}")
    
    response = VoiceResponse()
    
    # Connect to LiveKit room via SIP
    # This requires LiveKit SIP to be configured
    response.say(
        "Connecting you to DGX Spark Voice AI via SIP.",
        voice='Polly.Joanna'
    )
    
    # Dial into LiveKit SIP
    # Format: sip:room-name@your-livekit-sip-domain
    response.dial(f'sip:{LIVEKIT_ROOM}@cleans2s.voiceflow.cloud')
    
    return Response(str(response), mimetype='text/xml')


def create_sip_trunk():
    """
    Create a Twilio SIP trunk programmatically
    
    Run this once to set up the SIP trunk
    """
    if not twilio_client:
        logger.error("Twilio not configured")
        return
    
    try:
        # Create SIP trunk
        trunk = twilio_client.trunking.v1.trunks.create(
            friendly_name="DGX Spark Voice AI",
            domain_name="dgx-sip.voiceflow.cloud"
        )
        
        logger.info(f"Created SIP trunk: {trunk.sid}")
        
        # Configure origination (incoming calls to Twilio)
        origination_url = twilio_client.trunking.v1.trunks(trunk.sid).origination_urls.create(
            friendly_name="LiveKit Origination",
            sip_url=f"sip:cleans2s.voiceflow.cloud:5060",
            priority=1,
            weight=1
        )
        
        logger.info(f"Created origination: {origination_url.sid}")
        
        return trunk.sid
        
    except Exception as e:
        logger.error(f"Failed to create SIP trunk: {e}")
        return None


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info(f"Starting Twilio webhook server on port {port}")
    logger.info(f"LiveKit URL: {LIVEKIT_URL}")
    logger.info(f"Room: {LIVEKIT_ROOM}")
    
    # Run the Flask server
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )
