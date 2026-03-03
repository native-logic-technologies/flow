#!/usr/bin/env python3
"""LiveKit JWT Token Server - Fixed Version"""
import os
import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import jwt

app = FastAPI(title="DGX Spark Token Server", version="1.0.0")

# CORS - Allow all origins for testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# LiveKit Cloud credentials
LIVEKIT_API_KEY = "APIvYfuiEm6SszU"
LIVEKIT_API_SECRET = "nSZRwjePixsezNYpfZ2nvY0RbyEsufdfzqXkntDPxBuF"
LIVEKIT_URL = "wss://6aii08srz2e.livekit.cloud"

class TokenResponse(BaseModel):
    token: str
    url: str
    room: str
    identity: str

def generate_token_manual(room: str, identity: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=6)
    
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

@app.get("/api/token", response_model=TokenResponse)
async def generate_token(
    room: str = "dgx-demo-room", 
    identity: str = None,
    participant: str = None
):
    user_identity = participant or identity or f"user-{datetime.now().strftime('%H%M%S')}"
    
    try:
        token = generate_token_manual(room, user_identity)
        return TokenResponse(
            token=token,
            url=LIVEKIT_URL,
            room=room,
            identity=user_identity
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token generation failed: {str(e)}")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "livekit_url": LIVEKIT_URL,
        "api_key": LIVEKIT_API_KEY[:10] + "..."
    }

if __name__ == "__main__":
    print(f"🚀 Token Server: {LIVEKIT_URL}")
    uvicorn.run(app, host="0.0.0.0", port=8888)
