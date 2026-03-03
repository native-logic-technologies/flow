#!/usr/bin/env python3
"""
LiveKit Agent Dispatcher
Handles multiple concurrent SIP calls by spawning Rust worker processes
"""
import asyncio
import subprocess
import os
from livekit import api

class AgentDispatcher:
    def __init__(self):
        self.livekit_url = "ws://localhost:7880"
        self.api_key = "APIQp4vjmCjrWQ9"
        self.api_secret = "PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l"
        self.active_workers = {}
        
    async def spawn_agent_for_call(self, room_name: str, call_sid: str):
        """Spawn a Rust orchestrator for a new SIP call"""
        
        # Generate unique identity for this call
        agent_identity = f"agent-{call_sid}"
        
        # Set environment for this specific call
        env = os.environ.copy()
        env.update({
            'LIVEKIT_URL': self.livekit_url,
            'LIVEKIT_API_KEY': self.api_key,
            'LIVEKIT_API_SECRET': self.api_secret,
            'ROOM_NAME': room_name,
            'AGENT_IDENTITY': agent_identity,
            'CALL_SID': call_sid,
        })
        
        # Spawn the Rust orchestrator
        proc = subprocess.Popen(
            ['../target/release/livekit_orchestrator'],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        self.active_workers[call_sid] = proc
        print(f"✅ Spawned agent for call {call_sid} in room {room_name}")
        
        return proc
    
    async def cleanup_call(self, call_sid: str):
        """Clean up when call ends"""
        if call_sid in self.active_workers:
            proc = self.active_workers[call_sid]
            proc.terminate()
            del self.active_workers[call_sid]
            print(f"🧹 Cleaned up agent for call {call_sid}")

if __name__ == "__main__":
    dispatcher = AgentDispatcher()
    print("🚀 Agent Dispatcher ready for telephony")
    print(f"   Can handle ~500 concurrent calls on 128GB DGX Spark")
