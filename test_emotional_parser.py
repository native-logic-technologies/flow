#!/usr/bin/env python3
"""
Test the emotional prosody parser without full TTS
"""

import re
from typing import List
from dataclasses import dataclass

@dataclass
class EmotionalSentence:
    emotion: str
    text: str
    index: int = 0

class EmotionalProsodyParser:
    """Parse Brain output into emotional sentences"""
    
    EMOTION_MAP = {
        "excited": "excited",
        "happy": "happy", 
        "cheerful": "happy",
        "neutral": "neutral",
        "calm": "calm",
        "sad": "sad",
        "empathetic": "empathetic",
        "sympathetic": "empathetic",
        "serious": "serious",
        "urgent": "urgent",
        "thinking": "thinking",
    }
    
    @classmethod
    def parse(cls, text: str) -> List[EmotionalSentence]:
        """Parse [EMOTION: X] tagged text"""
        if not text or not text.strip():
            return []
        
        pattern = r'\[EMOTION:\s*(\w+)\]\s*([^\[]+?)(?=\[EMOTION:|$)'
        matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
        
        sentences = []
        for i, (emotion, sentence_text) in enumerate(matches):
            emotion = emotion.lower().strip()
            normalized = cls.EMOTION_MAP.get(emotion, "neutral")
            
            sub_sentences = cls._split_sentences(sentence_text.strip())
            for sub in sub_sentences:
                if sub.strip():
                    sentences.append(EmotionalSentence(
                        emotion=normalized,
                        text=sub.strip(),
                        index=len(sentences)
                    ))
        
        if not sentences and text.strip():
            clean_text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
            clean_text = re.sub(r'</think>', '', clean_text).strip()
            if clean_text:
                sentences.append(EmotionalSentence("neutral", clean_text, 0))
        
        return sentences
    
    @classmethod
    def _split_sentences(cls, text: str) -> List[str]:
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        return [s.strip() for s in sentences if s.strip()]

# Test cases
test_cases = [
    # Case 1: Single emotion
    "[EMOTION: HAPPY] That's wonderful news!",
    
    # Case 2: Multiple emotions
    "[EMOTION: EXCITED] I can't believe it! [EMOTION: HAPPY] This is amazing!",
    
    # Case 3: Multi-sentence with same emotion
    "[EMOTION: EMPATHETIC] I'm sorry to hear that. It must be difficult.",
    
    # Case 4: No emotion tag (fallback)
    "Just a plain response without emotion tags.",
    
    # Case 5: Complex mixed emotions
    "[EMOTION: THINKING] Hmm, let me think... [EMOTION: EXCITED] Oh, I got it! That's brilliant!",
]

print("╔═══════════════════════════════════════════════════════════════════════════════╗")
print("║         🎭 EMOTIONAL PROSODY PARSER TEST                                      ║")
print("╚═══════════════════════════════════════════════════════════════════════════════╝\n")

for i, test_input in enumerate(test_cases, 1):
    print(f"Test {i}: \"{test_input[:60]}...\"")
    print("-" * 60)
    
    sentences = EmotionalProsodyParser.parse(test_input)
    
    if sentences:
        for sent in sentences:
            print(f"  [{sent.index}] [EMOTION: {sent.emotion.upper()}] \"{sent.text}\"")
    else:
        print("  ⚠️  No sentences parsed")
    
    print()

print("✅ Parser validation complete!")
