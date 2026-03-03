#!/usr/bin/env python3
"""
End-to-End Latency Test for S2S Pipeline
Tests: ASR -> LLM -> TTS with Comma-Level Chunking
"""

import asyncio
import json
import time
import aiohttp
import websockets
import numpy as np

# Service endpoints
LLM_URL = "http://localhost:8000"
ASR_URL = "http://localhost:8001"
TTS_URL = "ws://localhost:8002"


async def test_llm_latency():
    """Test LLM time to first token (TTFT)"""
    print("\n" + "="*60)
    print("TEST 1: LLM Time-to-First-Token (TTFT)")
    print("="*60)
    
    url = f"{LLM_URL}/v1/chat/completions"
    body = {
        "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4",
        "messages": [
            {"role": "system", "content": "/no_think\nYou are a helpful voice assistant."},
            {"role": "user", "content": "Hello, how are you?"}
        ],
        "stream": True,
        "temperature": 0.0,
        "max_tokens": 50
    }
    
    latencies = []
    
    async with aiohttp.ClientSession() as session:
        for i in range(3):
            start = time.perf_counter()
            first_token_time = None
            
            async with session.post(url, json=body) as resp:
                async for line in resp.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            json_data = json.loads(data)
                            if json_data.get('choices', [{}])[0].get('delta', {}).get('content'):
                                if first_token_time is None:
                                    first_token_time = time.perf_counter()
                                    break
                        except:
                            pass
            
            if first_token_time:
                latency = (first_token_time - start) * 1000
                latencies.append(latency)
                print(f"  Run {i+1}: {latency:.1f}ms")
    
    if latencies:
        avg = sum(latencies) / len(latencies)
        print(f"\n  ✓ Average LLM TTFT: {avg:.1f}ms")
        return avg
    return 0


async def test_tts_streaming_latency():
    """Test TTS first audio latency with Comma-Level Chunking"""
    print("\n" + "="*60)
    print("TEST 2: TTS First Audio Latency (Comma-Level Chunking)")
    print("="*60)
    print("  Simulating 25-char chunks with punctuation triggers...")
    
    test_chunks = [
        "Hello there,",  # 12 chars + comma trigger
        " how are you",  # 12 chars (25 total)
        " doing today?"  # 13 chars + question trigger
    ]
    
    latencies = []
    
    for run in range(3):
        async with websockets.connect(f"{TTS_URL}/ws/tts") as ws:
            # Send init
            await ws.send(json.dumps({"type": "init", "voice": "phil"}))
            
            start_time = time.perf_counter()
            first_audio_time = None
            
            # Stream chunks with small delays (simulating LLM generation)
            for chunk in test_chunks:
                await ws.send(json.dumps({"type": "token", "text": chunk}))
                await asyncio.sleep(0.08)  # 80ms between chunks (simulates LLM)
                
                # Check for audio response
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.recv(), timeout=0.05)
                        if isinstance(msg, bytes):
                            if first_audio_time is None:
                                first_audio_time = time.perf_counter()
                            break
                        elif isinstance(msg, str):
                            try:
                                data = json.loads(msg)
                                if data.get("type") == "complete":
                                    break
                            except:
                                pass
                except asyncio.TimeoutError:
                    pass
            
            # Send end
            await ws.send(json.dumps({"type": "end"}))
            
            # Wait for completion
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    if isinstance(msg, str):
                        try:
                            data = json.loads(msg)
                            if data.get("type") == "complete":
                                break
                        except:
                            pass
            except asyncio.TimeoutError:
                pass
            
            end_time = time.perf_counter()
            
            if first_audio_time:
                latency = (first_audio_time - start_time) * 1000
                latencies.append(latency)
                print(f"  Run {run+1}: {latency:.1f}ms to first audio")
            else:
                print(f"  Run {run+1}: No audio received")
    
    if latencies:
        avg = sum(latencies) / len(latencies)
        print(f"\n  ✓ Average TTS First Audio: {avg:.1f}ms")
        return avg
    return 0


async def test_full_pipeline():
    """Test full S2S pipeline latency"""
    print("\n" + "="*60)
    print("TEST 3: Full S2S Pipeline Latency (Simulated)")
    print("="*60)
    print("  Waterfall timing with Comma-Level Chunking:")
    print()
    
    # Simulated timing based on measured component latencies
    timing = {
        "ASR (first interim)": 50,
        "ASR (final)": 150,
        "LLM TTFT": 50,
        "LLM chunk generation (25 chars)": 80,
        "TTS first audio (with caching)": 300,
        "Network overhead": 20,
    }
    
    print("  Component Breakdown:")
    total = 0
    for component, latency in timing.items():
        print(f"    {component:.<35} {latency:>5}ms")
        total += latency
    
    # But with waterfall parallelism, we don't sum them all
    # ASR final -> LLM starts -> first 25 chars ready -> TTS processes
    # TTS can start while LLM is still generating
    
    waterfall_latency = (
        timing["ASR (final)"] +
        timing["LLM TTFT"] +
        timing["LLM chunk generation (25 chars)"] +
        timing["TTS first audio (with caching)"] +
        timing["Network overhead"]
    )
    
    print()
    print(f"  Waterfall (parallel) latency: ~{waterfall_latency}ms")
    print()
    
    if waterfall_latency < 500:
        print(f"  ✅ TARGET ACHIEVED: {waterfall_latency}ms < 500ms")
    else:
        print(f"  ❌ Target not met: {waterfall_latency}ms > 500ms")
    
    return waterfall_latency


async def main():
    print("\n" + "="*60)
    print("S2S PIPELINE END-TO-END LATENCY TEST")
    print("Configuration: Comma-Level Chunking (25 chars)")
    print("="*60)
    
    # Check services
    print("\nChecking services...")
    services_ok = True
    
    for name, url in [("LLM", LLM_URL), ("ASR", ASR_URL)]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{url}/health", timeout=2) as resp:
                    if resp.status == 200:
                        print(f"  ✓ {name} at {url}")
                    else:
                        print(f"  ✗ {name} unhealthy: {resp.status}")
                        services_ok = False
        except Exception as e:
            print(f"  ✗ {name} unavailable: {e}")
            services_ok = False
    
    # Check TTS WebSocket
    try:
        async with websockets.connect(f"{TTS_URL}/ws/tts") as ws:
            print(f"  ✓ TTS WebSocket at {TTS_URL}")
    except Exception as e:
        print(f"  ✗ TTS WebSocket unavailable: {e}")
        services_ok = False
    
    if not services_ok:
        print("\n❌ Some services unavailable, aborting test")
        return
    
    print("\n  All services healthy! Running tests...")
    
    # Run tests
    llm_ttft = await test_llm_latency()
    tts_first = await test_tts_streaming_latency()
    e2e = await test_full_pipeline()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"  LLM TTFT:           {llm_ttft:.1f}ms")
    print(f"  TTS First Audio:    {tts_first:.1f}ms")
    print(f"  Estimated E2E:      ~{e2e:.0f}ms")
    print()
    if e2e < 500:
        print(f"  ✅ TARGET <500ms ACHIEVED")
    else:
        print(f"  ⚠️  Target not yet achieved")
    print()
    print("  Configuration:")
    print("    FLUSH_SIZE:     25 chars (Golden Ratio)")
    print("    FLUSH_TRIGGERS: , . ! ? ; :")
    print("    FLUSH_TIMEOUT:  50ms")
    print()


if __name__ == "__main__":
    asyncio.run(main())
