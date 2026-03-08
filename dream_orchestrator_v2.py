#!/usr/bin/env python3
"""
Dream Stack Orchestrator V2 - Sentence-Level Emotional Streaming

Proper emotional prosody implementation:
1. Brain (Nemotron) outputs [EMOTION: X] tagged sentences
2. Orchestrator parses into (emotion, sentence) tuples
3. Each sentence streamed to MOSS-TTS with emotion context
4. Natural prosody with emotional variation

Architecture:
- Port 8000: Nemotron-3-Nano-30B (Brain)
- Port 8001: Llama-Omni-7B (Ear) - Optional
- Port 8002: MOSS-TTS (Voice)
"""

import asyncio
import re
import time
import statistics
from typing import List, Tuple, Optional
from dataclasses import dataclass
import aiohttp

# ============== Configuration ==============

BRAIN_URL = "http://localhost:8000/v1/chat/completions"
VOICE_URL = "http://localhost:8002/v1/audio/speech"

# ============== Emotional Prosody Parser ==============

@dataclass
class EmotionalSentence:
    """A sentence with emotional context for proper prosody"""
    emotion: str
    text: str
    index: int = 0

class EmotionalProsodyParser:
    """
    Parse Brain output into emotional sentences for proper TTS prosody.
    
    Input:  "[EMOTION: EXCITED] That's amazing! [EMOTION: HAPPY] Great job!"
    Output: [EmotionalSentence("excited", "That's amazing!"), 
             EmotionalSentence("happy", "Great job!")]
    """
    
    # Emotion normalization map
    EMOTION_MAP = {
        # Direct mappings
        "excited": "excited",
        "happy": "happy", 
        "cheerful": "happy",
        "joyful": "happy",
        "neutral": "neutral",
        "calm": "calm",
        "sad": "sad",
        "empathetic": "empathetic",
        "sympathetic": "empathetic",
        "caring": "empathetic",
        "serious": "serious",
        "urgent": "urgent",
        "angry": "serious",
        "frustrated": "serious",
        "thinking": "thinking",
        "contemplative": "thinking",
        "surprised": "excited",
        "confused": "thinking",
    }
    
    @classmethod
    def parse(cls, text: str) -> List[EmotionalSentence]:
        """
        Parse text with [EMOTION: X] tags into emotional sentences.
        
        Handles:
        - Multiple emotions in one response
        - Sentence boundary detection
        - Missing emotion tags (defaults to neutral)
        """
        if not text or not text.strip():
            return []
        
        # Pattern: [EMOTION: X] sentence
        # Match emotion tag followed by text until next emotion tag or end
        pattern = r'\[EMOTION:\s*(\w+)\]\s*([^\[]+?)(?=\[EMOTION:|$)'
        matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
        
        sentences = []
        for i, (emotion, sentence_text) in enumerate(matches):
            emotion = emotion.lower().strip()
            sentence_text = sentence_text.strip()
            
            # Normalize emotion
            normalized_emotion = cls.EMOTION_MAP.get(emotion, "neutral")
            
            # Split into actual sentences if multiple in one emotion block
            sub_sentences = cls._split_sentences(sentence_text)
            for j, sub in enumerate(sub_sentences):
                if sub.strip():
                    sentences.append(EmotionalSentence(
                        emotion=normalized_emotion,
                        text=sub.strip(),
                        index=len(sentences)
                    ))
        
        # If no emotion tags found, treat as single neutral sentence
        if not sentences and text.strip():
            # Clean up any thinking tags
            clean_text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
            clean_text = re.sub(r'</think>', '', clean_text)
            clean_text = clean_text.strip()
            
            if clean_text:
                sentences.append(EmotionalSentence(
                    emotion="neutral",
                    text=clean_text,
                    index=0
                ))
        
        return sentences
    
    @classmethod
    def _split_sentences(cls, text: str) -> List[str]:
        """Split text into sentences while preserving punctuation"""
        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        return [s.strip() for s in sentences if s.strip()]

# ============== Dream Stack Orchestrator ==============

class DreamOrchestratorV2:
    """
    Orchestrates Brain → Voice with sentence-level emotional streaming.
    
    Key improvement: Each sentence gets its own emotion context for proper prosody.
    """
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.metrics = []
    
    async def start(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60)
        )
    
    async def stop(self):
        """Cleanup"""
        if self.session:
            await self.session.close()
    
    async def generate_with_emotion(
        self, 
        user_input: str,
        system_prompt: Optional[str] = None
    ) -> Tuple[str, List[EmotionalSentence], float]:
        """
        Generate response from Brain and parse into emotional sentences.
        
        Returns:
            (raw_response, emotional_sentences, generation_time_ms)
        """
        if system_prompt is None:
            system_prompt = """You are a friendly voice assistant having a natural conversation.

CRITICAL: Your response MUST start with [EMOTION: X] where X is one of: NEUTRAL, HAPPY, EXCITED, CALM, EMPATHETIC, SERIOUS, THINKING

If your response has multiple sentences with different emotions, use [EMOTION: X] before each sentence.

Examples:
[EMOTION: EXCITED] That's amazing news! I'm so happy for you!
[EMOTION: EMPATHETIC] I'm sorry to hear that. [EMOTION: CALM] Let's talk through this together.
[EMOTION: THINKING] Hmm, that's an interesting question. Let me think about it."""

        start_time = time.perf_counter()
        
        payload = {
            "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            "max_tokens": 150,
            "temperature": 0.7,
            "stream": False
        }
        
        async with self.session.post(BRAIN_URL, json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                raw_text = result["choices"][0]["message"]["content"]
                generation_time = (time.perf_counter() - start_time) * 1000
                
                # Parse into emotional sentences
                sentences = EmotionalProsodyParser.parse(raw_text)
                
                return raw_text, sentences, generation_time
            else:
                error = await resp.text()
                raise Exception(f"Brain error {resp.status}: {error[:200]}")
    
    async def synthesize_sentence(
        self, 
        sentence: EmotionalSentence,
        timeout: int = 30
    ) -> Tuple[bytes, float, float]:
        """
        Synthesize a single sentence with emotional context.
        
        Returns:
            (audio_bytes, ttfc_ms, total_ms)
        """
        # Add emotion tag for TTS prosody modeling
        text_with_emotion = f"[EMOTION: {sentence.emotion.upper()}] {sentence.text}"
        
        start_time = time.perf_counter()
        first_chunk_time = None
        audio_chunks = []
        
        payload = {
            "input": text_with_emotion,
            "voice": "phil",
            "response_format": "pcm",
            "temperature": self._emotion_to_temperature(sentence.emotion),
            "top_p": 0.6
        }
        
        async with self.session.post(VOICE_URL, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                error = await resp.text()
                raise Exception(f"TTS error {resp.status}: {error[:200]}")
            
            # Stream audio chunks
            async for chunk in resp.content.iter_chunked(4096):
                if chunk:
                    if first_chunk_time is None:
                        first_chunk_time = time.perf_counter()
                    audio_chunks.append(chunk)
        
        end_time = time.perf_counter()
        
        ttfc = (first_chunk_time - start_time) * 1000 if first_chunk_time else 0
        total = (end_time - start_time) * 1000
        audio = b"".join(audio_chunks)
        
        return audio, ttfc, total
    
    def _emotion_to_temperature(self, emotion: str) -> float:
        """Map emotion to TTS temperature for prosody variation"""
        temps = {
            "excited": 0.9,    # More variation for excitement
            "happy": 0.8,
            "neutral": 0.7,
            "calm": 0.6,
            "empathetic": 0.7,
            "serious": 0.5,    # Less variation for serious tone
            "thinking": 0.6,
        }
        return temps.get(emotion.lower(), 0.7)
    
    async def stream_conversation_turn(
        self, 
        user_input: str
    ) -> dict:
        """
        Process one conversation turn with proper emotional prosody.
        
        Flow:
        1. Generate response from Brain with emotion tags
        2. Parse into emotional sentences
        3. Stream each sentence to TTS with emotion context
        4. Yield audio chunks as they're ready
        
        Returns metrics dict.
        """
        metrics = {
            "user_input": user_input,
            "brain_generation_ms": 0,
            "sentences": [],
            "total_audio_bytes": 0,
            "time_to_first_audio_ms": 0,
            "total_time_ms": 0
        }
        
        turn_start = time.perf_counter()
        first_audio_time = None
        
        print(f"\n💬 User: \"{user_input}\"")
        
        # Step 1: Generate response from Brain
        try:
            raw_response, sentences, gen_time = await self.generate_with_emotion(user_input)
            metrics["brain_generation_ms"] = gen_time
            
            print(f"🧠 Brain ({gen_time:.1f}ms): \"{raw_response[:80]}...\"")
            print(f"   Parsed into {len(sentences)} emotional sentence(s)")
            
            for sent in sentences:
                print(f"   [{sent.index}] [EMOTION: {sent.emotion.upper()}] \"{sent.text}\"")
        
        except Exception as e:
            print(f"❌ Brain error: {e}")
            metrics["error"] = str(e)
            return metrics
        
        # Step 2: Stream each sentence to TTS
        total_audio_bytes = 0
        sentence_metrics = []
        
        for sentence in sentences:
            try:
                audio, ttfc, total = await self.synthesize_sentence(sentence)
                
                sent_metric = {
                    "index": sentence.index,
                    "emotion": sentence.emotion,
                    "text": sentence.text,
                    "ttfc_ms": ttfc,
                    "total_ms": total,
                    "audio_bytes": len(audio),
                    "audio_duration": len(audio) / (24000 * 2)  # 24kHz 16-bit
                }
                sentence_metrics.append(sent_metric)
                total_audio_bytes += len(audio)
                
                # Track first audio time
                if first_audio_time is None:
                    first_audio_time = time.perf_counter()
                    time_to_first = (first_audio_time - turn_start) * 1000
                    metrics["time_to_first_audio_ms"] = time_to_first
                    print(f"   ⏱️  First audio at {time_to_first:.1f}ms")
                
                print(f"   🎙️  [{sentence.index}] {sentence.emotion}: {ttfc:.1f}ms → {sent_metric['audio_duration']:.2f}s audio")
                
                # In real implementation, yield audio chunks here
                # yield audio
                
            except Exception as e:
                print(f"❌ TTS error for sentence {sentence.index}: {e}")
                sent_metric = {"index": sentence.index, "error": str(e)}
                sentence_metrics.append(sent_metric)
        
        turn_end = time.perf_counter()
        
        # Compile metrics
        metrics["sentences"] = sentence_metrics
        metrics["total_audio_bytes"] = total_audio_bytes
        metrics["total_time_ms"] = (turn_end - turn_start) * 1000
        
        return metrics

# ============== Benchmark ==============

async def benchmark_emotional_prosody():
    """Benchmark sentence-level emotional streaming"""
    
    print("╔═══════════════════════════════════════════════════════════════════════════════╗")
    print("║         🎭 DREAM STACK V2 - EMOTIONAL PROSODY BENCHMARK                       ║")
    print("║         Sentence-Level Streaming with Emotion Context                         ║")
    print("╚═══════════════════════════════════════════════════════════════════════════════╝\n")
    
    orchestrator = DreamOrchestratorV2()
    await orchestrator.start()
    
    # Test conversations with emotional variation
    test_inputs = [
        "I just got promoted at work!",
        "I'm feeling really sad about what happened.",
        "Wait, what? I can't believe that!",
        "Can you help me think through this problem?",
        "Thank you so much for your help!",
    ]
    
    all_metrics = []
    
    print("=" * 80)
    print("Running 5-turn conversational benchmark...")
    print("=" * 80)
    
    for i, user_input in enumerate(test_inputs, 1):
        print(f"\n{'='*80}")
        print(f"TURN {i}/5")
        print("=" * 80)
        
        metrics = await orchestrator.stream_conversation_turn(user_input)
        all_metrics.append(metrics)
        
        # Brief pause between turns
        await asyncio.sleep(0.3)
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 BENCHMARK SUMMARY")
    print("=" * 80)
    
    # Calculate statistics
    brain_times = [m["brain_generation_ms"] for m in all_metrics if "brain_generation_ms" in m]
    ttfas = [m["time_to_first_audio_ms"] for m in all_metrics if "time_to_first_audio_ms" in m]
    total_times = [m["total_time_ms"] for m in all_metrics if "total_time_ms" in m]
    
    def stats(vals):
        if not vals:
            return {"mean": 0, "min": 0, "max": 0, "p95": 0}
        sorted_vals = sorted(vals)
        return {
            "mean": statistics.mean(vals),
            "min": min(vals),
            "max": max(vals),
            "p95": sorted_vals[int(len(sorted_vals) * 0.95)] if len(sorted_vals) > 1 else sorted_vals[0]
        }
    
    brain_s = stats(brain_times)
    ttfa_s = stats(ttfas)
    total_s = stats(total_times)
    
    print(f"\n🏁 COMPONENT LATENCIES:")
    print(f"   Brain Generation:     {brain_s['mean']:.1f}ms avg (range: {brain_s['min']:.1f}-{brain_s['max']:.1f}ms)")
    print(f"   Time to First Audio:  {ttfa_s['mean']:.1f}ms avg (range: {ttfa_s['min']:.1f}-{ttfa_s['max']:.1f}ms)")
    print(f"   Total Turn Time:      {total_s['mean']:.1f}ms avg (range: {total_s['min']:.1f}-{total_s['max']:.1f}ms)")
    
    print(f"\n🎯 TARGET COMPARISON:")
    print(f"   Sesame Target:        650ms")
    print(f"   Our TTFA:             {ttfa_s['mean']:.1f}ms")
    
    if ttfa_s['mean'] <= 650:
        print(f"   Status:               ✅ UNDER TARGET by {650 - ttfa_s['mean']:.1f}ms!")
    else:
        print(f"   Status:               ⚠️  OVER TARGET by {ttfa_s['mean'] - 650:.1f}ms")
    
    print(f"\n🎭 EMOTIONAL PROSODY:")
    total_sentences = sum(len(m.get("sentences", [])) for m in all_metrics)
    print(f"   Total sentences:      {total_sentences}")
    print(f"   Avg per turn:         {total_sentences/len(all_metrics):.1f}")
    print(f"   Status:               ✅ Sentence-level with emotion context")
    
    print("\n" + "=" * 80)
    print("✅ BENCHMARK COMPLETE")
    print("=" * 80)
    
    await orchestrator.stop()
    return all_metrics

# ============== Main ==============

if __name__ == "__main__":
    try:
        asyncio.run(benchmark_emotional_prosody())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
