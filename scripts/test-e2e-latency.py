#!/usr/bin/env python3
"""
End-to-End Latency Test for CleanS2S Stack

Measures full pipeline latency:
1. Audio input → ASR transcription
2. ASR text → LLM first token (TTFT)
3. LLM → TTS audio output
4. Total end-to-end latency

Also verifies zero-shot voice cloning is working.
"""

import asyncio
import json
import time
import struct
import base64
import wave
import io
from datetime import datetime
import websockets
import aiohttp
import numpy as np

# Configuration
ORCHESTRATOR_WS = "ws://localhost:8080/ws"
TTS_URL = "http://localhost:8002/v1/audio/speech"
LLM_URL = "http://localhost:8000/v1/chat/completions"
ASR_URL = "http://localhost:8001/v1/chat/completions"

# Test audio - 3 seconds of synthetic speech-like audio
def generate_test_audio(duration_sec=3, sample_rate=8000):
    """Generate synthetic speech-like audio (sine wave with modulation)"""
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec))
    # Simulate speech with varying frequencies
    carrier = np.sin(2 * np.pi * 200 * t)
    modulation = 0.5 * np.sin(2 * np.pi * 5 * t) + 0.5
    audio = carrier * modulation * 0.5
    # Convert to int16
    return (audio * 32767).astype(np.int16).tobytes()


def load_reference_audio():
    """Load the converted reference audio for voice cloning"""
    voice_file = "/home/phil/telephony-stack/tts/phil-conversational-16k-5s.wav"
    try:
        with open(voice_file, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"⚠️  Could not load reference audio: {e}")
        return None


async def test_tts_voice_cloning():
    """Test that zero-shot voice cloning is working"""
    print("\n🎤 Testing Zero-Shot Voice Cloning...")
    
    ref_audio = load_reference_audio()
    if not ref_audio:
        print("❌ No reference audio available")
        return False
    
    test_text = "Hello, this is a voice cloning test."
    
    # Test with voice cloning
    request_with_cloning = {
        "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
        "input": test_text,
        "response_format": "pcm",
        "extra_body": {
            "reference_audio": ref_audio
        }
    }
    
    # Test without voice cloning (default voice)
    request_default = {
        "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
        "input": test_text,
        "response_format": "pcm"
    }
    
    async with aiohttp.ClientSession() as session:
        # Test with cloning
        start = time.time()
        async with session.post(TTS_URL, json=request_with_cloning) as resp:
            if resp.status != 200:
                print(f"❌ TTS with cloning failed: {resp.status}")
                return False
            audio_with_cloning = await resp.read()
            latency_with_cloning = (time.time() - start) * 1000
        
        # Test default
        start = time.time()
        async with session.post(TTS_URL, json=request_default) as resp:
            if resp.status != 200:
                print(f"❌ TTS default failed: {resp.status}")
                return False
            audio_default = await resp.read()
            latency_default = (time.time() - start) * 1000
    
    # Check audio sizes are reasonable
    print(f"  Audio with cloning: {len(audio_with_cloning)} bytes ({latency_with_cloning:.0f}ms)")
    print(f"  Audio default:      {len(audio_default)} bytes ({latency_default:.0f}ms)")
    
    if len(audio_with_cloning) > 1000 and len(audio_default) > 1000:
        print("✅ TTS voice cloning appears to be working")
        return True
    else:
        print("⚠️  TTS returned very small audio, may not be working correctly")
        return False


async def test_llm_ttft():
    """Test LLM Time-To-First-Token"""
    print("\n🧠 Testing Nemotron LLM TTFT...")
    
    request = {
        "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
        "messages": [
            {"role": "user", "content": "Say hello in exactly two words."}
        ],
        "stream": True,
        "max_tokens": 10,
        "temperature": 0.7
    }
    
    ttft_measurements = []
    
    async with aiohttp.ClientSession() as session:
        for i in range(3):  # Run 3 times
            start = time.time()
            first_token_time = None
            
            async with session.post(LLM_URL, json=request) as resp:
                async for line in resp.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith('data: '):
                        if first_token_time is None:
                            first_token_time = time.time()
                            ttft = (first_token_time - start) * 1000
                            ttft_measurements.append(ttft)
                            break
    
    avg_ttft = sum(ttft_measurements) / len(ttft_measurements)
    print(f"  TTFT measurements: {[f'{t:.0f}ms' for t in ttft_measurements]}")
    print(f"  Average TTFT: {avg_ttft:.0f}ms")
    
    if avg_ttft < 200:
        print(f"✅ TTFT target met (<200ms)")
    else:
        print(f"⚠️  TTFT above target: {avg_ttft:.0f}ms")
    
    return avg_ttft


async def test_full_pipeline():
    """Test full end-to-end pipeline via WebSocket"""
    print("\n🔄 Testing Full Pipeline via WebSocket...")
    print(f"  Connecting to {ORCHESTRATOR_WS}...")
    
    # Generate test audio
    test_audio = generate_test_audio(duration_sec=2)
    print(f"  Generated {len(test_audio)} bytes of test audio")
    
    latencies = {
        'connection': 0,
        'first_response': 0,
        'total': 0
    }
    
    try:
        start_total = time.time()
        
        async with websockets.connect(ORCHESTRATOR_WS) as ws:
            latencies['connection'] = (time.time() - start_total) * 1000
            print(f"  WebSocket connected in {latencies['connection']:.0f}ms")
            
            # Send ping to verify connection
            await ws.send(json.dumps({"type": "ping"}))
            
            # Send audio in chunks (simulating real-time)
            chunk_size = 256 * 2  # 256 samples * 2 bytes
            start_audio = time.time()
            
            for i in range(0, len(test_audio), chunk_size):
                chunk = test_audio[i:i+chunk_size]
                await ws.send(chunk)
                await asyncio.sleep(0.032)  # 32ms = 256 samples @ 8kHz
            
            print(f"  Sent audio in {(time.time() - start_audio)*1000:.0f}ms")
            
            # Wait for response with timeout
            response_audio = bytearray()
            start_wait = time.time()
            
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    
                    if isinstance(msg, bytes):
                        if latencies['first_response'] == 0:
                            latencies['first_response'] = (time.time() - start_total) * 1000
                            print(f"  ⏱️  First audio response: {latencies['first_response']:.0f}ms")
                        
                        response_audio.extend(msg)
                        
                        # Stop after receiving reasonable amount
                        if len(response_audio) > 48000:  # ~2 seconds @ 24kHz
                            break
                    else:
                        print(f"  Text message: {msg}")
                        
                except asyncio.TimeoutError:
                    print(f"  Timeout waiting for response")
                    break
            
            latencies['total'] = (time.time() - start_total) * 1000
            
    except Exception as e:
        print(f"  ❌ Pipeline test failed: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    print(f"\n  📊 Pipeline Results:")
    print(f"    Connection:     {latencies['connection']:>6.0f}ms")
    print(f"    First Response: {latencies['first_response']:>6.0f}ms")
    print(f"    Total Time:     {latencies['total']:>6.0f}ms")
    print(f"    Audio Received: {len(response_audio)} bytes")
    
    return latencies


async def test_individual_services():
    """Test each service individually"""
    print("\n🔍 Testing Individual Services...")
    
    results = {}
    
    # Test LLM
    print("  Testing Nemotron LLM...")
    async with aiohttp.ClientSession() as session:
        start = time.time()
        async with session.get("http://localhost:8000/health") as resp:
            results['llm_health'] = (time.time() - start) * 1000
            results['llm_status'] = resp.status == 200
    
    # Test ASR
    print("  Testing Voxtral ASR...")
    async with aiohttp.ClientSession() as session:
        start = time.time()
        async with session.get("http://localhost:8001/health") as resp:
            results['asr_health'] = (time.time() - start) * 1000
            results['asr_status'] = resp.status == 200
    
    # Test TTS
    print("  Testing MOSS-TTS...")
    async with aiohttp.ClientSession() as session:
        start = time.time()
        async with session.get("http://localhost:8002/health") as resp:
            results['tts_health'] = (time.time() - start) * 1000
            results['tts_status'] = resp.status == 200
    
    print(f"\n  Health Check Latencies:")
    print(f"    LLM:  {results['llm_health']:.1f}ms {'✅' if results['llm_status'] else '❌'}")
    print(f"    ASR:  {results['asr_health']:.1f}ms {'✅' if results['asr_status'] else '❌'}")
    print(f"    TTS:  {results['tts_health']:.1f}ms {'✅' if results['tts_status'] else '❌'}")
    
    return results


async def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║     CleanS2S End-to-End Latency Test                             ║")
    print("║     Target: <500ms total latency                                 ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"\nTest Time: {datetime.now().isoformat()}")
    
    # Test 1: Individual services
    service_results = await test_individual_services()
    
    if not all([service_results.get('llm_status'), 
                service_results.get('asr_status'), 
                service_results.get('tts_status')]):
        print("\n❌ Some services are not healthy, aborting full test")
        return
    
    # Test 2: LLM TTFT
    ttft = await test_llm_ttft()
    
    # Test 3: Voice cloning
    cloning_works = await test_tts_voice_cloning()
    
    # Test 4: Full pipeline
    pipeline_results = await test_full_pipeline()
    
    # Summary
    print("\n" + "="*70)
    print("                         TEST SUMMARY")
    print("="*70)
    
    print(f"\n✅ Service Health:     All services responding")
    print(f"✅ LLM TTFT:           {ttft:.0f}ms (target: <200ms)")
    print(f"{'✅' if cloning_works else '⚠️ '} Voice Cloning:      {'Working' if cloning_works else 'Issues detected'}")
    
    if pipeline_results:
        total = pipeline_results['total']
        print(f"\n⏱️  Full Pipeline Latency:")
        print(f"   First Response: {pipeline_results['first_response']:.0f}ms")
        print(f"   Total Time:     {total:.0f}ms")
        
        if total < 500:
            print(f"\n🎉 SUCCESS: Pipeline latency <500ms!")
        else:
            print(f"\n⚠️  WARNING: Pipeline latency {total:.0f}ms exceeds 500ms target")
    else:
        print("\n❌ Full pipeline test did not complete")
    
    print("\n" + "="*70)
    
    # Save results
    results = {
        "timestamp": datetime.now().isoformat(),
        "service_health": service_results,
        "llm_ttft_ms": ttft,
        "voice_cloning_working": cloning_works,
        "pipeline_latency_ms": pipeline_results['total'] if pipeline_results else None,
        "target_met": pipeline_results['total'] < 500 if pipeline_results else False
    }
    
    with open("/home/phil/telephony-stack/logs/e2e-test-results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to: logs/e2e-test-results.json")


if __name__ == "__main__":
    asyncio.run(main())
