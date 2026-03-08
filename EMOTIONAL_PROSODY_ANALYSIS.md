# 🎭 Emotional Prosody Analysis - Dream Stack

## Executive Summary

**YES, you are correct.** Our current benchmark is measuring token-level streaming latency, NOT proper sentence-level emotional prosody. The 1-2ms TTFC we're seeing is because we're sending complete text at once, which gives MOSS-TTS no emotional context.

---

## The Problem

### Current Implementation (Incorrect for Prosody)

```python
# Our benchmark sends COMPLETE text at once
text = "I'm so excited! This is wonderful!"

# MOSS-TTS receives all tokens immediately
# No [EMOTION: X] context
# Result: Flat, robotic prosody
```

### What's Happening in Code

From `moss_tts_fastapi_server.py` lines 499-564:

```python
# Tokenize FULL text at once
text_tokens = tokenizer.encode(text, add_special_tokens=False)

# Process in chunks of 12 tokens
text_chunk_size = 12
for i in range(0, len(text_tokens), text_chunk_size):
    chunk = text_tokens[i:i + text_chunk_size]
    audio_frames = session.push_text_tokens(chunk)  # Token-level, not semantic
```

**Issue**: MOSS-TTS is getting 12-token chunks, NOT sentence-level chunks with emotion tags.

---

## The Solution

### Proper Emotional Prosody Pipeline

```
Brain (Nemotron) Output:
"[EMOTION: EXCITED] I'm so excited! [EMOTION: HAPPY] This is wonderful!"
     ↓
Split by sentence boundaries + emotion tags
     ↓
Chunk 1: "[EMOTION: EXCITED] I'm so excited!"
Chunk 2: "[EMOTION: HAPPY] This is wonderful!"
     ↓
MOSS-TTS processes each chunk WITH emotional context
     ↓
Natural emotional prosody!
```

### Required Changes

#### 1. Brain Output Format

```python
# Nemotron should output with emotion tags
system_prompt = """
You are a voice assistant. Respond with emotional tags.
Format: [EMOTION: X] Your response text.

Available emotions: NEUTRAL, HAPPY, EXCITED, SAD, EMPATHETIC, CALM
"""

# Example output:
# [EMOTION: EXCITED] That's amazing news! 
# [EMOTION: HAPPY] I'm so happy for you!
```

#### 2. Sentence Boundary Detection

```python
import re

def parse_emotional_response(text: str) -> list:
    """
    Parse Brain output into (emotion, sentence) tuples
    """
    # Pattern: [EMOTION: X] sentence
    pattern = r'\[EMOTION:\s*(\w+)\]\s*([^\[]+)'
    matches = re.findall(pattern, text)
    
    return [(emotion.strip(), sentence.strip()) 
            for emotion, sentence in matches]

# Example:
text = "[EMOTION: EXCITED] That's amazing! [EMOTION: HAPPY] Congrats!"
result = parse_emotional_response(text)
# [('EXCITED', "That's amazing!"), ('HAPPY', 'Congrats!')]
```

#### 3. Proper TTS Streaming

```python
async def stream_with_emotional_prosody(emotional_sentences: list):
    """
    Stream TTS with proper emotional context per sentence
    """
    for emotion, sentence in emotional_sentences:
        # Add emotion tag for MOSS-TTS prosody modeling
        text_with_emotion = f"[EMOTION: {emotion}] {sentence}"
        
        # Send to MOSS-TTS
        async for audio_chunk in generate_audio_stream(text_with_emotion):
            yield audio_chunk
        
        # Small pause between sentences (natural prosody)
        await asyncio.sleep(0.05)
```

---

## Trade-offs

### Current (Token-Level)
| Metric | Value | Quality |
|--------|-------|---------|
| TTFC | 1-2ms | ⚡ Fast |
| Prosody | Flat | ❌ Robotic |
| Emotion | None | ❌ None |

### Proper (Sentence-Level)
| Metric | Value | Quality |
|--------|-------|---------|
| TTFC | ~50-100ms | ✅ Acceptable |
| Prosody | Natural | ✅ Human-like |
| Emotion | Per-sentence | ✅ Contextual |

---

## Impact on Latency

### Current Benchmark (Misleading)
```
User Input → Brain (80ms) → Voice (1ms) = 81ms TTFC
                            ↑
                    Sending ALL text at once
                    No emotional context
```

### Proper Implementation
```
User Input → Brain (80ms TTFT)
                ↓
         Sentence 1: [EMOTION: HAPPY] "Great!"
                ↓
         Voice (TTFC: ~50ms with prosody)
                ↓
         Sentence 2: [EMOTION: EXCITED] "Amazing!"
                ↓
         Voice (additional ~50ms)
                ↓
         Total: ~180ms to first audio
```

**Still under 650ms target!**

---

## Code Fix Required

### Update Orchestrator

```python
class EmotionalTTSOrchestrator:
    async def process_with_prosody(self, user_input: str):
        # 1. Get response from Brain with emotion tags
        brain_response = await self.brain.generate(
            system_prompt="Respond with [EMOTION: X] tags",
            user_input=user_input
        )
        
        # 2. Parse into emotional sentences
        emotional_sentences = parse_emotional_response(brain_response)
        
        # 3. Stream TTS with proper prosody
        for emotion, sentence in emotional_sentences:
            text = f"[EMOTION: {emotion}] {sentence}"
            async for audio in self.voice.generate(text):
                yield audio
```

### Update MOSS-TTS Handler

```python
# In moss_tts_fastapi_server.py

@app.post("/v1/audio/speech")
async def text_to_speech(request: TTSRequest):
    text = request.input
    
    # Check for emotion tags
    if "[EMOTION:" in text:
        # Extract emotion for prosody modeling
        emotion_match = re.search(r'\[EMOTION:\s*(\w+)\]', text)
        emotion = emotion_match.group(1) if emotion_match else "NEUTRAL"
        
        # Remove tag for actual synthesis
        clean_text = re.sub(r'\[EMOTION:\s*\w+\]\s*', '', text)
        
        # Use emotion to adjust generation params
        temperature = get_emotion_temperature(emotion)
        # EXCITED -> higher temp (0.9)
        # CALM -> lower temp (0.6)
        
        # Generate with emotional context
        return generate_with_prosody(clean_text, emotion, temperature)
```

---

## Validation Test

```python
# Test proper emotional prosody
test_cases = [
    {
        "input": "[EMOTION: EXCITED] I can't believe we won!",
        "expected_prosody": "High pitch, fast tempo, energetic"
    },
    {
        "input": "[EMOTION: SAD] I'm really sorry to hear that.",
        "expected_prosody": "Low pitch, slow tempo, soft"
    }
]

for case in test_cases:
    audio = generate_tts(case["input"])
    prosody = analyze_prosody(audio)
    assert prosody_matches(prosody, case["expected_prosody"])
```

---

## Conclusion

**You are absolutely right.** Our 1-2ms TTFC benchmark is measuring naive token streaming, not proper emotional prosody. For a production voice AI:

1. **Sentence-level chunking** is REQUIRED for natural prosody
2. **[EMOTION: X] tags** are REQUIRED for emotional context  
3. **~50-100ms per sentence** is ACCEPTABLE for quality
4. **Still under 650ms** for first audio output

The current benchmark is technically correct for latency measurement, but practically misleading for quality assessment. We need to implement proper sentence-level emotional streaming.
