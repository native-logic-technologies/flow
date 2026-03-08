#!/usr/bin/env python3
"""
Dream Stack Conversational Test with proper prompts
"""

import time
import requests
import json
import statistics

BRAIN_URL = "http://localhost:8000/v1/chat/completions"
VOICE_URL = "http://localhost:8002/generate"

# Proper conversational prompts
CONVERSATION = [
    ("user", "Hey there, how's it going?"),
    ("assistant", None),  # Will be generated
    ("user", "I'm doing great! What have you been up to?"),
    ("assistant", None),
    ("user", "Tell me something interesting."),
    ("assistant", None),
]

class ConversationalTest:
    def __init__(self):
        self.history = []
        self.latencies = []
    
    def get_response(self, user_msg: str) -> tuple:
        """Get response from Nemotron with conversation history"""
        self.history.append({"role": "user", "content": user_msg})
        
        messages = [
            {"role": "system", "content": "You are a friendly, conversational AI. Respond naturally in 1-2 sentences."}
        ] + self.history
        
        start = time.perf_counter()
        
        response = requests.post(
            BRAIN_URL,
            json={
                "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
                "messages": messages,
                "max_tokens": 50,
                "temperature": 0.8,
                "stream": True
            },
            timeout=30,
            stream=True
        )
        
        first_token = None
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
                            if first_token is None:
                                first_token = time.perf_counter()
                            full_text += delta
                    except:
                        pass
        
        end = time.perf_counter()
        
        ttft = (first_token - start) * 1000 if first_token else (end - start) * 1000
        total = (end - start) * 1000
        
        # Add to history
        self.history.append({"role": "assistant", "content": full_text.strip()})
        
        return ttft, total, full_text.strip()
    
    def speak(self, text: str) -> float:
        """Convert text to speech"""
        start = time.perf_counter()
        
        response = requests.post(
            VOICE_URL,
            json={
                "text": text[:100],
                "speaker_id": "phil",
                "stream": True
            },
            timeout=30,
            stream=True
        )
        
        first_chunk = None
        for chunk in response.iter_content(chunk_size=4096):
            if chunk and first_chunk is None:
                first_chunk = time.perf_counter()
        
        ttfc = (first_chunk - start) * 1000 if first_chunk else 0
        return ttfc
    
    def run(self):
        print("╔═══════════════════════════════════════════════════════════════════════════════╗")
        print("║         💬 DREAM STACK - CONVERSATIONAL LATENCY TEST                          ║")
        print("╚═══════════════════════════════════════════════════════════════════════════════╝\n")
        
        test_inputs = [
            "Hey there! How's it going?",
            "What have you been working on lately?",
            "Tell me something interesting about AI.",
            "That sounds cool! Can you explain more?",
            "Thanks for the chat! Goodbye!",
        ]
        
        for i, user_msg in enumerate(test_inputs, 1):
            print(f"\n💬 Turn {i}")
            print(f"   User: \"{user_msg}\"")
            
            # Get LLM response
            ttft, total, response = self.get_response(user_msg)
            print(f"   Assistant: \"{response[:60]}...\"")
            
            # Get TTS
            voice_ttfc = self.speak(response)
            
            # Total to first audio
            total_to_audio = ttft + voice_ttfc
            self.latencies.append(total_to_audio)
            
            print(f"   ⚡ Latency: {total_to_audio:.1f}ms (Brain: {ttft:.1f}ms, Voice: {voice_ttfc:.1f}ms)")
            time.sleep(0.2)
        
        # Summary
        print("\n" + "═" * 80)
        print("📊 RESULTS")
        print("═" * 80)
        
        mean_lat = statistics.mean(self.latencies)
        min_lat = min(self.latencies)
        max_lat = max(self.latencies)
        
        print(f"\n   Time to First Audio:")
        print(f"   • Min:  {min_lat:.1f}ms")
        print(f"   • Mean: {mean_lat:.1f}ms")
        print(f"   • Max:  {max_lat:.1f}ms")
        print(f"\n   🎯 vs Sesame Target (650ms): {mean_lat:.1f}ms ({(mean_lat/650)*100:.1f}%)")
        
        if mean_lat <= 650:
            print(f"   ✅ UNDER TARGET by {650-mean_lat:.1f}ms!")
        
        print("\n" + "═" * 80)

if __name__ == "__main__":
    test = ConversationalTest()
    test.run()
