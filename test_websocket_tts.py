#!/usr/bin/env python3
"""
Test WebSocket TTS streaming between LLM and MOSS-TTS
This tests the <500ms latency pipeline.
"""

import asyncio
import json
import time
import websockets

async def test_websocket_tts():
    """Test the WebSocket TTS streaming endpoint directly."""
    
    print("Testing MOSS-TTS WebSocket streaming...")
    print("=" * 60)
    
    # Connect to MOSS-TTS WebSocket
    tts_ws_url = "ws://localhost:8002/ws/tts"
    
    start_time = time.time()
    
    async with websockets.connect(tts_ws_url) as ws:
        connect_time = time.time() - start_time
        print(f"✓ Connected to TTS WebSocket ({connect_time*1000:.1f}ms)")
        
        # Send init message
        await ws.send(json.dumps({
            "type": "init",
            "voice": "default"
        }))
        
        # Wait for ready
        response = await ws.recv()
        status = json.loads(response)
        if status.get("status") != "ready":
            print(f"✗ TTS not ready: {status}")
            return
        
        ready_time = time.time() - start_time
        print(f"✓ TTS ready ({ready_time*1000:.1f}ms)")
        
        # Test text to synthesize
        test_text = "Hello, this is a test of the WebSocket TTS streaming."
        
        # Stream text in chunks (simulating LLM token generation)
        chunk_size = 5
        for i in range(0, len(test_text), chunk_size):
            chunk = test_text[i:i+chunk_size]
            await ws.send(json.dumps({
                "type": "text",
                "text": chunk
            }))
            await asyncio.sleep(0.01)  # Small delay between chunks
        
        text_sent_time = time.time() - start_time
        print(f"✓ Text streamed ({text_sent_time*1000:.1f}ms)")
        
        # Send end
        await ws.send(json.dumps({"type": "end"}))
        
        # Receive audio chunks
        audio_chunks = 0
        total_bytes = 0
        first_audio_time = None
        
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                
                if isinstance(msg, bytes):
                    audio_chunks += 1
                    total_bytes += len(msg)
                    if first_audio_time is None:
                        first_audio_time = time.time() - start_time
                        print(f"✓ First audio chunk received ({first_audio_time*1000:.1f}ms)")
                else:
                    status = json.loads(msg)
                    if status.get("status") == "complete":
                        complete_time = time.time() - start_time
                        print(f"✓ TTS complete ({complete_time*1000:.1f}ms)")
                        print(f"  - Total audio chunks: {audio_chunks}")
                        print(f"  - Total bytes: {total_bytes}")
                        print(f"  - Audio duration: ~{total_bytes / 48000:.2f}s (24kHz PCM)")
                        break
                    elif status.get("error"):
                        print(f"✗ TTS error: {status}")
                        break
                        
            except asyncio.TimeoutError:
                print("✗ Timeout waiting for TTS response")
                break
        
        if first_audio_time:
            print(f"\n📊 Latency Results:")
            print(f"  - Connection: {connect_time*1000:.1f}ms")
            print(f"  - TTS ready: {ready_time*1000:.1f}ms")
            print(f"  - First audio: {first_audio_time*1000:.1f}ms")
            print(f"  - Total: {complete_time*1000:.1f}ms")
            
            if first_audio_time < 0.5:
                print(f"\n✅ SUCCESS: <500ms latency achieved!")
            else:
                print(f"\n⚠️  First audio >500ms, but still streaming")


async def test_full_pipeline():
    """Test the full orchestrator pipeline with WebSocket streaming."""
    
    print("\nTesting full orchestrator pipeline...")
    print("=" * 60)
    
    orchestrator_ws = "ws://localhost:8080/ws"
    
    start_time = time.time()
    
    async with websockets.connect(orchestrator_ws) as ws:
        connect_time = time.time() - start_time
        print(f"✓ Connected to orchestrator ({connect_time*1000:.1f}ms)")
        
        # Send a text message (simulating ASR result)
        await ws.send(json.dumps({
            "type": "text",
            "text": "What time is it?"
        }))
        
        text_sent_time = time.time() - start_time
        print(f"✓ Text sent ({text_sent_time*1000:.1f}ms)")
        
        # Wait for response
        message_count = 0
        first_response_time = None
        audio_chunks = 0
        
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                data = json.loads(msg)
                
                if first_response_time is None:
                    first_response_time = time.time() - start_time
                    print(f"✓ First response received ({first_response_time*1000:.1f}ms)")
                
                message_count += 1
                
                if data.get("type") == "audio":
                    audio_chunks += 1
                    if audio_chunks == 1:
                        first_audio_time = time.time() - start_time
                        print(f"✓ First audio received ({first_audio_time*1000:.1f}ms)")
                
                if data.get("type") == "response_chunk" and data.get("done"):
                    complete_time = time.time() - start_time
                    print(f"✓ Response complete ({complete_time*1000:.1f}ms)")
                    print(f"  - Total messages: {message_count}")
                    print(f"  - Audio chunks: {audio_chunks}")
                    break
                    
            except asyncio.TimeoutError:
                print("✗ Timeout waiting for response")
                break
        
        if first_response_time:
            print(f"\n📊 Full Pipeline Latency:")
            print(f"  - Connection: {connect_time*1000:.1f}ms")
            print(f"  - First response: {first_response_time*1000:.1f}ms")
            if audio_chunks > 0:
                print(f"  - First audio: {first_audio_time*1000:.1f}ms")
            print(f"  - Total: {complete_time*1000:.1f}ms")


async def main():
    print("WebSocket TTS Streaming Test")
    print("=" * 60)
    print()
    
    # Test direct TTS WebSocket
    await test_websocket_tts()
    
    # Test full pipeline
    # await test_full_pipeline()  # Uncomment to test full pipeline
    
    print("\n✅ Tests complete!")


if __name__ == "__main__":
    asyncio.run(main())
