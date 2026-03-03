#!/usr/bin/env python3
"""Test the full orchestrator pipeline with WebSocket TTS"""

import asyncio
import json
import websockets

async def test_full_pipeline():
    """Test text -> LLM -> TTS through orchestrator"""
    
    print("Testing Full Pipeline (Orchestrator WebSocket)")
    print("=" * 60)
    
    orchestrator_ws = "ws://localhost:8080/ws"
    
    try:
        async with websockets.connect(orchestrator_ws) as ws:
            print("✓ Connected to orchestrator")
            
            # Send a text message (simulating ASR result)
            await ws.send(json.dumps({
                "type": "text",
                "text": "Hello! How are you today?"
            }))
            print("✓ Sent text message")
            
            # Wait for response
            message_count = 0
            audio_chunks = 0
            
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    data = json.loads(msg)
                    message_count += 1
                    
                    msg_type = data.get("type")
                    
                    if msg_type == "audio":
                        audio_chunks += 1
                        if audio_chunks == 1:
                            print(f"✓ First audio chunk received!")
                        if audio_chunks % 10 == 0:
                            print(f"  ... received {audio_chunks} audio chunks")
                    
                    elif msg_type == "response_chunk":
                        if data.get("done"):
                            print(f"✓ Response complete")
                            print(f"  Total messages: {message_count}")
                            print(f"  Audio chunks: {audio_chunks}")
                            break
                    
                    elif msg_type == "error":
                        print(f"✗ Error: {data.get('message')}")
                        break
                        
                except asyncio.TimeoutError:
                    print("✗ Timeout waiting for response")
                    break
            
            print("\n✅ Pipeline test complete!")
            
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_full_pipeline())
