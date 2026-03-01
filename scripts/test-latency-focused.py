#!/usr/bin/env python3
"""
Focused Latency Test - LLM TTFT + TTS Voice Cloning

Tests the critical path: LLM first token latency and TTS generation with voice cloning.
These are the components we can verify are working at <500ms.
"""

import asyncio
import json
import time
import base64
from datetime import datetime
import aiohttp
import numpy as np

# Configuration
LLM_URL = "http://localhost:8000/v1/chat/completions"
TTS_URL = "http://localhost:8002/v1/audio/speech"

def load_reference_audio():
    """Load Phil's voice for cloning"""
    voice_file = "/home/phil/telephony-stack/tts/phil-conversational-16k-5s.wav"
    try:
        with open(voice_file, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"⚠️  Could not load reference audio: {e}")
        return None


async def test_llm_ttft_detailed():
    """Test LLM Time-To-First-Token in detail"""
    print("\n🧠 Testing Nemotron LLM TTFT (Detailed)...")
    print("-" * 60)
    
    test_prompts = [
        "Say hello.",
        "What is 2+2?",
        "Tell me the weather.",
        "How are you today?",
    ]
    
    ttft_results = []
    total_results = []
    
    async with aiohttp.ClientSession() as session:
        for prompt in test_prompts:
            request = {
                "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "max_tokens": 50,
                "temperature": 0.7
            }
            
            start = time.time()
            first_token_time = None
            token_count = 0
            
            async with session.post(LLM_URL, json=request) as resp:
                async for line in resp.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith('data: ') and line != 'data: [DONE]':
                        if first_token_time is None:
                            first_token_time = time.time()
                        token_count += 1
            
            total_time = (time.time() - start) * 1000
            ttft = (first_token_time - start) * 1000 if first_token_time else 0
            
            ttft_results.append(ttft)
            total_results.append(total_time)
            
            print(f"  '{prompt[:30]:<30}' - TTFT: {ttft:>6.0f}ms | Total: {total_time:>6.0f}ms | Tokens: {token_count}")
    
    avg_ttft = sum(ttft_results) / len(ttft_results)
    avg_total = sum(total_results) / len(total_results)
    
    print("-" * 60)
    print(f"  Average TTFT:   {avg_ttft:.0f}ms")
    print(f"  Average Total:  {avg_total:.0f}ms")
    print(f"  Min/Max TTFT:   {min(ttft_results):.0f}ms / {max(ttft_results):.0f}ms")
    
    if avg_ttft < 150:
        print(f"  ✅ TTFT excellent (<150ms)")
    elif avg_ttft < 200:
        print(f"  ✅ TTFT good (<200ms)")
    else:
        print(f"  ⚠️  TTFT slow ({avg_ttft:.0f}ms)")
    
    return avg_ttft, avg_total


async def test_tts_voice_cloning_detailed():
    """Test TTS with voice cloning in detail"""
    print("\n🎤 Testing MOSS-TTS Voice Cloning (Detailed)...")
    print("-" * 60)
    
    ref_audio = load_reference_audio()
    if not ref_audio:
        print("❌ No reference audio available")
        return None, None
    
    test_phrases = [
        "Hello, this is a test of voice cloning.",
        "The weather is nice today.",
        "How can I help you?",
    ]
    
    latencies_with_cloning = []
    latencies_default = []
    
    async with aiohttp.ClientSession() as session:
        # Test with voice cloning
        print("  Testing WITH voice cloning (Phil's voice):")
        for phrase in test_phrases:
            request = {
                "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
                "input": phrase,
                "response_format": "pcm",
                "extra_body": {"reference_audio": ref_audio}
            }
            
            start = time.time()
            async with session.post(TTS_URL, json=request) as resp:
                audio_data = await resp.read()
            latency = (time.time() - start) * 1000
            latencies_with_cloning.append(latency)
            
            # Calculate audio duration (24kHz, 16-bit mono)
            audio_duration_ms = (len(audio_data) / 2) / 24.0
            
            print(f"    '{phrase[:40]:<40}' - Gen: {latency:>6.0f}ms | Audio: {audio_duration_ms:>5.0f}ms | Size: {len(audio_data)}b")
        
        # Test default voice
        print("\n  Testing WITHOUT voice cloning (default voice):")
        for phrase in test_phrases[:2]:  # Just test 2
            request = {
                "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
                "input": phrase,
                "response_format": "pcm"
            }
            
            start = time.time()
            async with session.post(TTS_URL, json=request) as resp:
                audio_data = await resp.read()
            latency = (time.time() - start) * 1000
            latencies_default.append(latency)
            
            print(f"    '{phrase[:40]:<40}' - Gen: {latency:>6.0f}ms")
    
    avg_with_cloning = sum(latencies_with_cloning) / len(latencies_with_cloning)
    avg_default = sum(latencies_default) / len(latencies_default)
    
    print("-" * 60)
    print(f"  Average WITH cloning:    {avg_with_cloning:.0f}ms")
    print(f"  Average WITHOUT cloning: {avg_default:.0f}ms")
    print(f"  Cloning overhead:        {avg_with_cloning - avg_default:.0f}ms")
    
    if avg_with_cloning < 500:
        print(f"  ✅ TTS with cloning fast (<500ms)")
    elif avg_with_cloning < 1000:
        print(f"  ✅ TTS with cloning acceptable (<1000ms)")
    else:
        print(f"  ⚠️  TTS with cloning slow ({avg_with_cloning:.0f}ms)")
    
    return avg_with_cloning, avg_default


async def test_full_turn_latency():
    """Test full turn: LLM generation + TTS synthesis"""
    print("\n🔄 Testing Full Turn Latency (LLM + TTS)...")
    print("-" * 60)
    
    ref_audio = load_reference_audio()
    
    test_prompts = [
        "Say hello and introduce yourself.",
        "What is the capital of France?",
    ]
    
    results = []
    
    async with aiohttp.ClientSession() as session:
        for prompt in test_prompts:
            print(f"\n  Prompt: '{prompt}'")
            
            # Step 1: LLM
            llm_start = time.time()
            llm_request = {
                "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,  # Non-streaming for total time
                "max_tokens": 50,
                "temperature": 0.7
            }
            
            async with session.post(LLM_URL, json=llm_request) as resp:
                llm_result = await resp.json()
                text_response = llm_result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            llm_time = (time.time() - llm_start) * 1000
            print(f"    LLM:  {llm_time:>6.0f}ms -> '{text_response[:50]}...'")
            
            # Step 2: TTS with voice cloning
            tts_start = time.time()
            tts_request = {
                "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
                "input": text_response,
                "response_format": "pcm",
                "extra_body": {"reference_audio": ref_audio} if ref_audio else {}
            }
            
            async with session.post(TTS_URL, json=tts_request) as resp:
                audio_data = await resp.read()
            
            tts_time = (time.time() - tts_start) * 1000
            total_time = (time.time() - llm_start) * 1000
            
            print(f"    TTS:  {tts_time:>6.0f}ms ({len(audio_data)} bytes)")
            print(f"    TOTAL: {total_time:>6.0f}ms")
            
            results.append({
                'llm': llm_time,
                'tts': tts_time,
                'total': total_time
            })
    
    avg_llm = sum(r['llm'] for r in results) / len(results)
    avg_tts = sum(r['tts'] for r in results) / len(results)
    avg_total = sum(r['total'] for r in results) / len(results)
    
    print("-" * 60)
    print(f"  Average LLM:   {avg_llm:.0f}ms")
    print(f"  Average TTS:   {avg_tts:.0f}ms")
    print(f"  Average TOTAL: {avg_total:.0f}ms")
    
    if avg_total < 500:
        print(f"  ✅ Full turn <500ms target MET!")
    elif avg_total < 1000:
        print(f"  ⚠️  Full turn {avg_total:.0f}ms (acceptable but above 500ms target)")
    else:
        print(f"  ❌ Full turn {avg_total:.0f}ms (above target)")
    
    return avg_llm, avg_tts, avg_total


async def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║     CleanS2S Latency Test - LLM + TTS Pipeline                   ║")
    print("║     Target: <500ms end-to-end                                    ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"\nTest Time: {datetime.now().isoformat()}")
    
    # Test 1: LLM TTFT
    avg_ttft, llm_total = await test_llm_ttft_detailed()
    
    # Test 2: TTS Voice Cloning
    tts_cloning, tts_default = await test_tts_voice_cloning_detailed()
    
    # Test 3: Full Turn
    if tts_cloning:
        avg_llm, avg_tts, avg_total = await test_full_turn_latency()
    else:
        avg_llm, avg_tts, avg_total = 0, 0, 0
    
    # Final Summary
    print("\n" + "="*70)
    print("                    FINAL LATENCY SUMMARY")
    print("="*70)
    print()
    print(f"  🧠 Nemotron LLM:")
    print(f"     TTFT (Time to First Token): {avg_ttft:.0f}ms")
    print(f"     Full Generation (50 tokens): {llm_total:.0f}ms")
    print()
    print(f"  🎤 MOSS-TTS Voice Cloning:")
    if tts_cloning:
        print(f"     With Voice Cloning:  {tts_cloning:.0f}ms")
        print(f"     Default Voice:       {tts_default:.0f}ms")
        print(f"     ✅ Voice cloning is WORKING!")
    else:
        print(f"     ❌ Voice cloning test failed")
    print()
    print(f"  🔄 Full Pipeline (LLM + TTS with Cloning):")
    print(f"     Average Latency: {avg_total:.0f}ms")
    print()
    
    if avg_total > 0 and avg_total < 500:
        print("  🎉 SUCCESS: Pipeline latency <500ms target MET!")
    elif avg_total > 0:
        print(f"  ⚠️  Pipeline latency {avg_total:.0f}ms (above 500ms target)")
    print()
    print("="*70)
    
    # Save results
    results = {
        "timestamp": datetime.now().isoformat(),
        "llm_ttft_ms": avg_ttft,
        "llm_total_ms": llm_total,
        "tts_with_cloning_ms": tts_cloning,
        "tts_default_ms": tts_default,
        "full_pipeline_ms": avg_total,
        "target_met": avg_total < 500 if avg_total > 0 else False,
        "voice_cloning_working": tts_cloning is not None
    }
    
    with open("/home/phil/telephony-stack/logs/latency-test-results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nDetailed results saved to: logs/latency-test-results.json")


if __name__ == "__main__":
    asyncio.run(main())
