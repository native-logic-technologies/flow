#!/usr/bin/env python3
"""
LiveKit JWT Token Server
Generates secure tokens for frontend connections to DGX Spark pipeline

Port: 8080 (replaces old orchestrator)
Endpoint: POST /api/token
"""

import os
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# Try to use livekit-server-sdk, fallback to manual JWT if not available
try:
    from livekit.api import AccessToken
    USE_LIVEKIT_SDK = True
except ImportError:
    USE_LIVEKIT_SDK = False
    import jwt
    print("Warning: livekit-server-sdk not found, using PyJWT fallback")

app = FastAPI(title="DGX Spark Token Server", version="1.0.0")

# CORS - Allow requests from your Vercel domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://*.vercel.app",  # All Vercel deployments
        "https://voiceflow.cloud",
        "https://*.voiceflow.cloud",
        "http://localhost:3000",  # Local development
        "http://localhost:5173",  # Vite default
    ],
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

# LiveKit credentials from environment
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "APIQp4vjmCjrWQ9")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://cleans2s.voiceflow.cloud")


class TokenRequest(BaseModel):
    room: str = "dgx-demo-room"
    identity: str = None  # Optional, will generate if not provided


class TokenResponse(BaseModel):
    token: str
    url: str
    room: str
    identity: str


def generate_token_manual(room: str, identity: str) -> str:
    """Generate JWT manually if livekit-server-sdk not available"""
    now = datetime.utcnow()
    exp = now + timedelta(hours=6)  # 6 hour expiry
    
    payload = {
        "iss": LIVEKIT_API_KEY,
        "sub": identity,
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
    
    return jwt.encode(payload, LIVEKIT_API_SECRET, algorithm="HS256")


def generate_token_sdk(room: str, identity: str) -> str:
    """Generate token using livekit-server-sdk"""
    token = AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, identity=identity)
    token.add_grant({
        "roomJoin": True,
        "room": room,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
    })
    return token.to_jwt()


@app.post("/api/token", response_model=TokenResponse)
async def generate_token(request: TokenRequest):
    """Generate a LiveKit JWT token for the frontend"""
    
    # Generate identity if not provided
    identity = request.identity or f"user-{datetime.now().strftime('%Y%m%d%H%M%S')}-{os.urandom(2).hex()}"
    
    try:
        # Generate token
        if USE_LIVEKIT_SDK:
            token = generate_token_sdk(request.room, identity)
        else:
            token = generate_token_manual(request.room, identity)
        
        return TokenResponse(
            token=token,
            url=LIVEKIT_URL,
            room=request.room,
            identity=identity
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token generation failed: {str(e)}")


@app.get("/api/token")
async def generate_token_get(room: str = "dgx-demo-room", identity: str = None):
    """GET endpoint for token generation (convenience)"""
    return await generate_token(TokenRequest(room=room, identity=identity))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "token-server",
        "livekit_url": LIVEKIT_URL,
        "sdk": "livekit-server-sdk" if USE_LIVEKIT_SDK else "pyjwt-fallback"
    }


@app.get("/")
async def root():
    """Root endpoint with info"""
    return {
        "service": "DGX Spark Token Server",
        "version": "1.0.0",
        "endpoints": {
            "token": "POST /api/token",
            "health": "GET /health"
        },
        "livekit_url": LIVEKIT_URL
    }


if __name__ == "__main__":
    print(f"🚀 Token Server starting on port 8080")
    print(f"   LiveKit URL: {LIVEKIT_URL}")
    print(f"   API Key: {LIVEKIT_API_KEY[:10]}...")
    print(f"   SDK: {'livekit-server-sdk' if USE_LIVEKIT_SDK else 'pyjwt-fallback'}")
    
    uvicorn.run(app, host="0.0.0.0", port=8080)
