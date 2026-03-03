#!/usr/bin/env python3
"""
Simple LiveKit Token Server
Generates valid JWT tokens for LiveKit connections
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import jwt
import time
from urllib.parse import parse_qs, urlparse

# LiveKit configuration
API_KEY = "APIQp4vjmCjrWQ9"
API_SECRET = "PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l"
ROOM_NAME = "dgx-spark-room"

class TokenHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/token":
            # Get participant name from query
            params = parse_qs(parsed.query)
            participant = params.get("participant", ["user-" + str(int(time.time()))])[0]
            
            # Generate token
            now = int(time.time())
            token = jwt.encode(
                {
                    "exp": now + 3600,
                    "iss": API_KEY,
                    "sub": participant,
                    "nbf": now,
                    "video": {
                        "roomJoin": True,
                        "room": ROOM_NAME,
                        "canPublish": True,
                        "canSubscribe": True,
                        "canPublishData": True
                    }
                },
                API_SECRET,
                algorithm="HS256"
            )
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "token": token,
                "room": ROOM_NAME,
                "participant": participant
            }).encode())
            
        elif parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"LiveKit Token Server\nEndpoints:\n  /token?participant=NAME\n")
            
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        print(f"[TokenServer] {self.address_string()} - {format % args}")

if __name__ == "__main__":
    port = 9001
    server = HTTPServer(("0.0.0.0", port), TokenHandler)
    print(f"Token server running on http://localhost:{port}")
    print(f"Get token: http://localhost:{port}/token?participant=test-user")
    server.serve_forever()
