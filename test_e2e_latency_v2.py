#!/usr/bin/env python3
"""
Dream Stack E2E Latency Test V2 - Optimized
- Streaming for faster TTFT
- Better prompts to reduce reasoning
- Temperature 0 for deterministic output
"""

import time
import requests
import json
import statistics
from typing import Dict, Tuple

BRAIN_URL = "http://localhost:8000/v1/chat/completions"
VOICE_URL = "http://localhost:8002/generate"
EAR_URL = "http://localhost:8001/v1/chat/completions"

# Better system prompts to strip reasoning
BRAIN_SYSTEM_PROMPT = """You are a voice assistant. Respond briefly and naturally. 
IMPORTANT: Start your response immediately with the answer. Do not explain your thinking."""

class OptimizedLatencyTest:
    def __init__(self):
        self.results = []
    
    def test_brain_streaming(self, text: str) -> Tuple[float, float, str]:
        """Test Brain with streaming - measure TTFT and total"""
        start = time.perf_counter()
        
        response = requests.post(
            BRAIN_URL,
            json={
                "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
                "messages": [
                    {"role": "system", "content": BRAIN_SYSTEM_PROMPT},
                    {"role": "user", "content": text}
                ],
                "max_tokens": 50,  # Shorter responses
                "temperature": 0.0,  # Deterministic
                "stream": True
            },
            timeout=30,
            stream=True
        )
        
        ttft = None
        full_text = ""
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]
                    if data == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk['choices'][0]['delta'].get('content', '')
                        if delta:
                            if ttft is None:
                                ttft = time.perf_counter()
                            full_text += delta
                    except:
                        pass
        
        end = time.perf_counter()
        
        ttft_ms = (ttft - start) * 1000 if ttft else (end - start) * 1000
        total_ms = (end - start) * 1000
        
        return ttft_ms, total_ms, full_text.strip()
    
    def test_voice_streaming(self, text: str) -> Tuple[float, float, int]:
        """Test Voice streaming - TTFC and total"""
        start = time.perf_counter()
        
        response = requests.post(
            VOICE_URL,
            json={
                "text": text[:100],  # Limit text length
                "speaker_id": "phil",
                "stream": True
            },
            timeout=30,
            stream=True
        )
        
        first_chunk_time = None
        total_bytes = 0
        
        for chunk in response.iter_content(chunk_size=4096):
            if chunk:
                if first_chunk_time is None:
                    first_chunk_time = time.perf_counter()
                total_bytes += len(chunk)
        
        end_time = time.perf_counter()
        
        ttfc_ms = (first_chunk_time - start) * 1000 if first_chunk_time else 0
        total_ms = (end_time - start) * 1000
        
        return ttfc_ms, total_ms, total_bytes
    
    def test_ear_optimized(self, text: str) -> Tuple[float, str]:
        """Test Ear with minimal output"""
        start = time.perf_counter()
        
        # Simulate a transcription with emotion extraction
        # In real use, this would be actual audio->text
        response = requests.post(
            EAR_URL,
            json={
                "model": "Qwen2.5-Omni-7B-q8_0.gguf",
                "messages": [
                    {"role": "system", "content": "Extract emotion and transcribe. Output format: [EMOTION: X] transcription"},
                    {"role": "user", "content": text}
                ],
                "max_tokens": 30,
                "temperature": 0.0
            },
            timeout=10
        )
        
        latency = (time.perf_counter() - start) * 1000
        
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            return latency, content
        else:
            return latency, text
    
    def run_single_test(self, input_text: str, i: int) -> Dict:
        """Run optimized pipeline test"""
        print(f"\n🔄 Test {i+1}: {input_text[:50]}...")
        
        result = {}
        
        # Step 1: Ear (simulated ASR)
        ear_lat, ear_out = self.test_ear_optimized(input_text)
        result['ear_ms'] = ear_lat
        print(f"  👂 Ear: {ear_lat:.1f}ms")
        
        # Step 2: Brain (streaming LLM)
        brain_ttft, brain_total, brain_text = self.test_brain_streaming(ear_out)
        result['brain_ttft_ms'] = brain_ttft
        result['brain_total_ms'] = brain_total
        result['brain_text'] = brain_text[:80]
        print(f"  🧠 Brain: TTFT={brain_ttft:.1f}ms, Total={brain_total:.1f}ms")
        print(f"      Output: '{brain_text[:60]}...'")
        
        # Step 3: Voice (streaming TTS)
        voice_ttfc, voice_total, audio_bytes = self.test_voice_streaming(brain_text)
        result['voice_ttfc_ms'] = voice_ttfc
        result['voice_total_ms'] = voice_total
        result['audio_bytes'] = audio_bytes
        result['audio_secs'] = audio_bytes / (24000 * 2)
        print(f"  🎙️  Voice: TTFC={voice_ttfc:.1f}ms, Audio={result['audio_secs']:.1f}s")
        
        # Pipeline metrics
        result['pipeline_to_audio_ms'] = ear_lat + brain_ttft + voice_ttfc
        result['total_ms'] = ear_lat + brain_total + voice_total
        
        print(f"  ⚡ Pipeline to audio: {result['pipeline_to_audio_ms']:.1f}ms")
        
        return result
    
    def run(self):
        print("╔═══════════════════════════════════════════════════════════════════════════════╗")
        print("║           🚀 DREAM STACK LATENCY TEST v2 - OPTIMIZED                          ║")
        print("╚═══════════════════════════════════════════════════════════════════════════════╝")
        
        # Verify services
        for name, url in [("Ear", EAR_URL), ("Brain", BRAIN_URL), ("Voice", VOICE_URL)]:
            try:
                requests.get(url.replace('/v1/chat/completions', '/health').replace('/generate', '/health'), timeout=2)
                print(f"  ✅ {name}")
            except:
                print(f"  ❌ {name} offline")
                return
        
        # Test inputs
        inputs = [
            "Hello, how are you today?",
            "What's the weather like?",
            "Tell me a joke.",
            "What time is it?",
            "Goodbye!",
        ]
        
        print("\n" + "═" * 80)
        for i, inp in enumerate(inputs):
            result = self.run_single_test(inp, i)
            self.results.append(result)
            time.sleep(0.3)
        
        # Summary
        print("\n" + "═" * 80)
        print("📊 SUMMARY")
        print("═" * 80)
        
        ear = [r['ear_ms'] for r in self.results]
        brain_ttft = [r['brain_ttft_ms'] for r in self.results]
        brain_total = [r['brain_total_ms'] for r in self.results]
        voice_ttfc = [r['voice_ttfc_ms'] for r in self.results]
        pipeline = [r['pipeline_to_audio_ms'] for r in self.results]
        
        def avg(vals):
            return statistics.mean(vals) if vals else 0
        
        print(f"\n  👂 Ear (ASR):          {avg(ear):.1f}ms avg")
        print(f"  🧠 Brain TTFT:         {avg(brain_ttft):.1f}ms avg")
        print(f"  🧠 Brain Total:        {avg(brain_total):.1f}ms avg")
        print(f"  🎙️  Voice TTFC:         {avg(voice_ttfc):.1f}ms avg")
        print(f"\n  ⚡ PIPELINE TO AUDIO:  {avg(pipeline):.1f}ms avg")
        print(f"\n  🎯 Sesame Target:      650ms")
        print(f"  📊 Gap:                {avg(pipeline) - 650:+.1f}ms ({(avg(pipeline)/650 - 1)*100:+.1f}%)")

if __name__ == "__main__":
    test = OptimizedLatencyTest()
    test.run()
