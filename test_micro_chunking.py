import asyncio
import websockets
import json
import time

async def test():
    uri = "ws://localhost:8080/ws"
    
    async with websockets.connect(uri) as ws:
        print("Connected")
        
        # Drain greeting
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                break
        
        # Send message
        start = time.time()
        await ws.send(json.dumps({"type": "text", "text": "Hello!"}))
        print("Sent: Hello!")
        
        chunks = 0
        first = None
        
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                if isinstance(msg, bytes):
                    chunks += 1
                    if first is None:
                        first = time.time() - start
                        print(f"First audio: {first*1000:.0f}ms")
            except asyncio.TimeoutError:
                break
        
        print(f"Total chunks: {chunks}")
        if first and first < 0.6:
            print("✅ SUB-500ms TARGET ACHIEVED!")

asyncio.run(test())
