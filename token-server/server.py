import os
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import jwt

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CORRECT LiveKit Cloud credentials
LIVEKIT_API_KEY = "APIvYfuiEm6SszU"
LIVEKIT_API_SECRET = "nSZRwjePixsezNYpfZ2nvY0RbyEsufdfzqXkntDPxBuF"
LIVEKIT_URL = "wss://6aii08srz2e.livekit.cloud"

class TokenResponse(BaseModel):
    token: str
    url: str
    room: str
    identity: str

@app.get("/api/token")
async def get_token(room: str = "dgx-demo-room", participant: str = None):
    identity = participant or f"user-{datetime.now().strftime('%H%M%S')}"
    now = datetime.now(timezone.utc)
    
    payload = {
        "iss": LIVEKIT_API_KEY,
        "sub": identity,
        "nbf": int(now.timestamp()),
        "exp": int(now.timestamp() + 6*3600),
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        }
    }
    
    token = jwt.encode(payload, LIVEKIT_API_SECRET, algorithm="HS256")
    return {"token": token, "url": LIVEKIT_URL, "room": room, "identity": identity}

@app.get("/health")
async def health():
    return {"status": "ok", "url": LIVEKIT_URL}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)
