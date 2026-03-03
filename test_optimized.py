import asyncio
import websockets
import json
import time

async def test():
    uri = "ws://localhost:8080/ws"
    
    async with websockets.connect(uri) as ws:
        print("✓ Connected")
        
        # Drain greeting
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                break
        
        # Test with short message
        start = time.time()
        await ws.send(json.dumps({"type": "text", "text": "Hi"}))
        print("Sent: 'Hi'")
        
        chunks = 0
        first = None
        
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                if isinstance(msg, bytes):
                    chunks += 1
                    if first is None:
                        first = time.time() - start
                        print(f"✓ First audio: {first*1000:.0f}ms")
                else:
                    if '"done"' in msg:
                        print(f"  Complete signal received")
                        break
            except asyncio.TimeoutError:
                break
        
        print(f"  Total chunks: {chunks}")
        if first:
            print(f"\n🎯 Latency: {first*1000:.0f}ms")
            if first < 0.6:
                print("✅ SUB-600ms! Close to target!")
            elif first < 1.0:
                print("✅ Sub-second (good!)")
            else:
                print("⚠️  Still optimizing...")

asyncio.run(test())
