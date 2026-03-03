#!/usr/bin/env python3
"""
LiveKit JWT Token Server for DGX Spark
Generates secure tokens for frontend connections
"""

import os
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import jwt

app = FastAPI(title="LiveKit Token Server", version="1.0.0")

# CORS - Allow requests from frontend domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://flow.speak.ad",
        "https://*.vercel.app",
        "https://*.voiceflow.cloud",
        "http://localhost:3000",
        "http://localhost:5173",
        "*",  # Allow all during development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# LiveKit Cloud credentials
LIVEKIT_API_KEY = "APINRueCWzvzw9X"
LIVEKIT_API_SECRET = "FijhXTfgg7yXDWmG9oeWEgaebdIIfCtWuGTVy9SoAeuA"
LIVEKIT_URL = "wss://ari-7m62wwj7.livekit.cloud"


class TokenResponse(BaseModel):
    token: str
    url: str
    room: str
    identity: str


@app.get("/")
async def root():
    return {"status": "LiveKit Token Server running", "livekit_url": LIVEKIT_URL}


@app.get("/api/token")
async def generate_token_get(room: str = "dgx-demo-room", identity: str = None):
    """Generate token via GET request"""
    user_identity = identity or f"user-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Generate JWT manually
    now = datetime.utcnow()
    exp = now + timedelta(hours=6)
    
    payload = {
        "iss": LIVEKIT_API_KEY,
        "sub": user_identity,
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        }
    }
    
    token = jwt.encode(payload, LIVEKIT_API_SECRET, algorithm="HS256")
    
    return {
        "token": token,
        "url": LIVEKIT_URL,
        "room": room,
        "identity": user_identity
    }


@app.post("/api/token")
async def generate_token_post(room: str = "dgx-demo-room", identity: str = None):
    """Generate token via POST request"""
    return await generate_token_get(room, identity)


@app.options("/api/token")
async def token_options():
    """Handle CORS preflight"""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)
