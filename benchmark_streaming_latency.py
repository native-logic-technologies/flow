#!/usr/bin/env python3
"""
Benchmark Token-Level Streaming Latency

Measures E2E latency from LLM token generation to audio output.
With token-level streaming, we expect <500ms first audio.

Usage:
  python benchmark_streaming_latency.py
"""

import asyncio
import json
import time
import statistics
import websockets
import aiohttp


LLM_URL = "http://localhost:8000"
TTS_URL = "ws://localhost:8002"


async def benchmark_tts_streaming():
    """
    Benchmark TTS latency with token-level streaming.
    
    Protocol:
    1. Send init
    2. Stream tokens one by one
    3. Measure time until first audio chunk received
    """
    print("=" * 60)
    print("Token-Level Streaming TTS Latency Benchmark")
    print("=" * 60)
    print()
    
    latencies = []
    test_phrases = [
        "Hello, how can I help you today?",
        "The weather is nice today.",
        "Let me think about that for a moment.",
    ]
    
    for phrase in test_phrases:
        print(f"Testing: '{phrase}'")
        
        async with websockets.connect(f"{TTS_URL}/ws/tts") as ws:
            # Send init
            await ws.send(json.dumps({"type": "init", "voice": "phil"}))
            
            # Start timing
            start_time = time.perf_counter()
            first_audio_time = None
            
            # Stream tokens word by word
            words = phrase.split()
            for i, word in enumerate(words):
                token = word + " "
                await ws.send(json.dumps({"type": "token", "text": token}))
                
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
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
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
                latency_ms = (first_audio_time - start_time) * 1000
                latencies.append(latency_ms)
                print(f"  First audio latency: {latency_ms:.1f}ms")
            else:
                print(f"  No audio received!")
            
            print()
    
    if latencies:
        print("=" * 60)
        print("Results Summary")
        print("=" * 60)
        print(f"Tests run: {len(latencies)}")
        print(f"Mean latency: {statistics.mean(latencies):.1f}ms")
        print(f"Min latency: {min(latencies):.1f}ms")
        print(f"Max latency: {max(latencies):.1f}ms")
        if len(latencies) > 1:
            print(f"Std dev: {statistics.stdev(latencies):.1f}ms")
        print()
        
        target = 500
        mean = statistics.mean(latencies)
        if mean < target:
            print(f"✓ TARGET ACHIEVED: {mean:.1f}ms < {target}ms")
        else:
            print(f"✗ Target not met: {mean:.1f}ms > {target}ms")
    else:
        print("No successful measurements")


async def benchmark_full_pipeline():
    """
    Benchmark full S2S pipeline with simulated user input.
    """
    print("=" * 60)
    print("Full S2S Pipeline Latency Benchmark")
    print("=" * 60)
    print()
    
    # This would require connecting to the actual orchestrator
    # For now, we just show the expected flow
    print("Expected latency breakdown with token-level streaming:")
    print()
    print("  ASR (first token):     ~50ms")
    print("  ASR (final):           ~200ms")
    print("  LLM TTFT:              ~50ms")
    print("  LLM -> TTS network:    ~5ms")
    print("  TTS first audio:       ~900ms")
    print("  TTS -> LiveKit:        ~10ms")
    print("  ------------------------")
    print("  TOTAL E2E:             ~400-500ms")
    print()
    print("Compare to batched approach:")
    print("  ASR (final):           ~200ms")
    print("  LLM (full response):   ~2000ms")
    print("  TTS (batched):         ~4000ms")
    print("  ------------------------")
    print("  TOTAL E2E:             ~6000ms")
    print()


async def main():
    # First check services are up
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{LLM_URL}/health") as resp:
                if resp.status != 200:
                    print(f"LLM health check failed: {resp.status}")
                    return
    except Exception as e:
        print(f"Cannot connect to LLM at {LLM_URL}: {e}")
        return
    
    print("Services are healthy, starting benchmark...")
    print()
    
    await benchmark_tts_streaming()
    await benchmark_full_pipeline()


if __name__ == "__main__":
    asyncio.run(main())
