# Emotional Metadata Bridge Architecture

## Overview

The **Emotional Metadata Bridge** is a sophisticated S2S (Speech-to-Speech) pipeline that preserves emotional context across ASR → Brain → TTS, creating truly human-like interactions.

### Why This Matters

In a standard cascaded S2S stack:
```
Audio → ASR (text) → Brain (text) → TTS (audio)
```

**Emotion is lost at each step!** The text "I'm fine" could mean:
- Genuine contentment
- Sarcastic frustration  
- Hesitant worry

Without emotion metadata, the AI responds inappropriately, breaking the illusion of human conversation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Emotional Metadata Bridge                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  🎤 ASR (Port 8001)                                                │
│  Qwen2.5-Omni                                                       │
│  Output: [FRUSTRATED] "My screen went blank!"                      │
│                    ↓                                                │
│  Emotion Extraction: Detects pitch, hesitation, tone               │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                    ↓                                                │
│  User Emotion: FRUSTRATED                                          │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                    ↓                                                │
│  🧠 Brain (Port 8000)                                              │
│  Qwen3.5-9B                                                         │
│  Input: "[FRUSTRATED] My screen went blank!"                       │
│  Output: <EMPATHETIC> "Oh no... I'm so sorry. Let's fix this."    │
│                    ↓                                                │
│  Emotional Reasoning: Matches response tone to user's state        │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                    ↓                                                │
│  Response Emotion: EMPATHETIC                                      │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                    ↓                                                │
│  🎙️ TTS (Port 8002)                                                 │
│  MOSS-TTS-Realtime                                                  │
│  Voice Cache: empathetic_voice.wav                                 │
│  Output: [Soft, caring tone] "Oh no... I'm so sorry..."           │
│                    ↓                                                │
│  Emotional Voice Cloning: Tone matches the empathetic words        │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                    ↓                                                │
│  📞 User hears: A genuinely concerned AI voice                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Emotion Chain Mapping

| User Emotion (ASR) | Brain Response | TTS Voice | Use Case |
|-------------------|----------------|-----------|----------|
| `[NEUTRAL]` | `<NEUTRAL>` | `neutral` | General conversation |
| `[FRUSTRATED]` | `<EMPATHETIC>` | `empathetic` | User is upset/angry |
| `[JOYFUL]` | `<CHEERFUL>` | `cheerful` | User is happy/excited |
| `[HESITANT]` | `<THINKING>` | `thinking` | User is uncertain |
| `[URGENT]` | `<URGENT>` | `urgent` | User is stressed/rushed |
| `[CONFUSED]` | `<EMPATHETIC>` | `empathetic` | User is lost/unsure |

---

## Components

### 1. ASR with Emotion Extraction (Port 8001)

**Model:** Qwen2.5-Omni  
**File:** `asr_emotion_server.py`

**Key Features:**
- Native audio understanding (not just text)
- Detects pitch variations, hesitation markers, speech rate
- Outputs emotion tag + transcription

**API:**
```bash
POST /v1/audio/transcriptions
{
  "audio": "base64_encoded_wav",
  "format": "wav"
}

Response:
{
  "text": "My screen went blank!",
  "emotion": "FRUSTRATED",
  "full_output": "[FRUSTRATED] \"My screen went blank!\""
}
```

**Emotions Detected:**
- `NEUTRAL` - Normal speech
- `FRUSTRATED` - Annoyed, angry
- `JOYFUL` - Happy, excited
- `HESITANT` - Uncertain, pausing
- `URGENT` - Rushed, stressed
- `CONFUSED` - Lost, questioning

---

### 2. Brain with Emotional Reasoning (Port 8000)

**Model:** Qwen3.5-9B  
**File:** `brain_emotion_server.py`

**Key Features:**
- Receives user emotion as context
- Generates emotionally appropriate responses
- Prefixes response with `<EMOTION>` tag

**System Prompt:**
```
You are Phil, a helpful and empathetic AI assistant.
Prefix your response with an emotional tone tag:
<EMPATHETIC> - For frustrated/upset users
<CHEERFUL> - For happy/positive contexts
<THINKING> - When analyzing or considering
<URGENT> - For serious/time-sensitive matters
<NEUTRAL> - For general conversation
```

**API:**
```bash
POST /v1/chat/completions
{
  "messages": [...],
  "user_emotion": "FRUSTRATED"
}

Response Headers:
  X-Response-Emotion: EMPATHETIC

Body:
{
  "choices": [{
    "message": {
      "content": "Oh no... I'm so sorry. Let's fix this."
    }
  }]
}
```

**Response Emotions:**
- `<EMPATHETIC>` - Soft, caring, understanding
- `<CHEERFUL>` - Happy, upbeat, positive
- `<PROFESSIONAL>` - Business, technical, formal
- `<THINKING>` - Contemplative, measured
- `<URGENT>` - Serious, focused, important
- `<NEUTRAL>` - Balanced, general

---

### 3. TTS with Emotional Voice Caching (Port 8002)

**Model:** MOSS-TTS-Realtime  
**File:** `tts_moss_realtime_server.py`

**Key Features:**
- Zero-shot voice cloning with reference audio
- Multiple voice caches for different emotions
- Voice emotion matches the response emotion

**Voice Cache System:**
```
voices/
├── neutral/reference.wav      ← Default voice
├── empathetic/reference.wav   ← Soft, lower pitch
├── cheerful/reference.wav     ← Higher energy, smiling
├── thinking/reference.wav     ← Measured, pauses
└── urgent/reference.wav       ← Faster, more focused
```

**Why Reference Audio Matters:**
MOSS-TTS-Realtime clones the **acoustic characteristics** of the reference:
- Pitch and tone
- Speaking speed
- Energy level
- Pausing patterns

If you use a cheerful reference with empathetic text, it sounds confused and robotic. **The voice must match the emotion!**

**API:**
```bash
POST /v1/audio/speech
{
  "input": "Oh no... I'm so sorry.",
  "voice": "empathetic",  # or "emotion": "empathetic"
  "response_format": "pcm"
}

Response:
  Content-Type: audio/pcm
  X-Emotion: empathetic
  X-Duration: 2.5
  [24kHz PCM audio data]
```

---

### 4. Emotional Orchestrator (Port 8080)

**File:** `emotional_orchestrator.py`

**Key Features:**
- Routes emotions between services
- Manages conversation history with emotion context
- Handles Twilio WebSocket streaming

**Emotion Flow:**
```python
# 1. ASR extracts user emotion
user_emotion, user_text = await transcribe_with_emotion(audio)
# → [FRUSTRATED] "My screen went blank!"

# 2. Brain generates emotional response
response_emotion, response_text = await generate_emotional_response(
    session, user_text, user_emotion
)
# → <EMPATHETIC> "Oh no... I'm so sorry. Let's fix this."

# 3. TTS uses matching voice
await synthesize_emotional(session, response_text, response_emotion)
# → Uses empathetic voice cache
```

---

## Voice Sample Recording Guide

### Prerequisites
- Good microphone (headset preferred)
- Quiet environment
- Natural speaking voice

### Recording Process

For each emotion, record a 3.5-second sample:

**1. Neutral Voice**
```
"Hi, I'm Phil. I'm here to help you with any questions you have."
```
- Normal speaking pace
- Balanced tone
- Friendly but professional

**2. Empathetic Voice**
```
"Oh, I understand... that must be really frustrating for you."
```
- Softer volume
- Slightly lower pitch
- Slower pace
- Genuine concern

**3. Cheerful Voice**
```
"That's wonderful news! I'm so happy to hear that!"
```
- Higher energy
- Smile while speaking (lifts pitch)
- Faster pace
- Enthusiasm

**4. Thinking Voice**
```
"Hmm... let me think about that for a moment... umm..."
```
- Measured pace
- Natural pauses
- Slightly hesitant
- Contemplative

**5. Urgent Voice**
```
"This is important - we need to address this immediately."
```
- Faster pace
- More focused tone
- Serious energy
- Direct

### Technical Specs
- **Format:** WAV
- **Sample Rate:** 24kHz
- **Channels:** Mono
- **Duration:** 3.0-4.0 seconds
- **Bit Depth:** 16-bit

### File Locations
```
/home/phil/telephony-stack/voices/
├── neutral/reference.wav
├── empathetic/reference.wav
├── cheerful/reference.wav
├── thinking/reference.wav
└── urgent/reference.wav
```

---

## Usage

### Start the Stack
```bash
cd /home/phil/telephony-stack
./start_emotional_stack.sh
```

### Test Individual Services

**Test ASR:**
```bash
curl -X POST http://localhost:8001/v1/audio/transcriptions \
  -H "Content-Type: application/json" \
  -d '{
    "audio": "base64_encoded_audio_here",
    "format": "wav"
  }'
```

**Test Brain:**
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "I am frustrated!"}],
    "user_emotion": "FRUSTRATED"
  }'
```

**Test TTS:**
```bash
curl -X POST http://localhost:8002/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Oh no... I am so sorry to hear that.",
    "voice": "empathetic"
  }' \
  --output test_audio.pcm

# Play audio
ffplay -f s16le -ar 24000 -ac 1 test_audio.pcm
```

---

## Performance Characteristics

| Component | Latency | VRAM Usage |
|-----------|---------|------------|
| ASR (Qwen2.5-Omni) | ~500ms | ~8 GB |
| Brain (Qwen3.5-9B) | ~200ms | ~6 GB |
| TTS (MOSS-Realtime) | ~800ms | ~10 GB |
| **Total E2E** | **~1.5s** | **~24 GB** |

*Note: Latencies are for short utterances (<5s audio, <30 tokens)*

---

## Troubleshooting

### TTS Sounds Robotic
**Cause:** Missing voice samples or emotion mismatch  
**Fix:** Record and place reference audio files in `voices/{emotion}/`

### Emotions Not Detected
**Cause:** ASR model not loaded or audio quality poor  
**Fix:** Check ASR logs (`tail -f /tmp/asr.log`)

### Brain Ignores Emotion
**Cause:** System prompt not emphasizing emotion tags  
**Fix:** Verify brain server is using emotional reasoning prompt

### High Latency
**Cause:** Models competing for GPU  
**Fix:** Ensure sufficient VRAM (24GB+) or use model quantization

---

## Advanced: Custom Emotions

To add a new emotion (e.g., `EXCITED`):

1. **ASR:** Add to emotion list in `asr_emotion_server.py`
2. **Brain:** Add to response emotions in `brain_emotion_server.py`
3. **TTS:** Create `voices/excited/reference.wav`
4. **Orchestrator:** Add mapping in `EMOTION_CHAIN`

---

## Comparison: Standard vs Emotional Stack

### Standard Stack (No Emotion)
```
User: [angry voice] "This is broken!"
ASR: "This is broken"
Brain: "I can help you with that."
TTS: [cheerful voice] "I can help you with that!"
User: 😠 (feels unheard)
```

### Emotional Stack
```
User: [angry voice] "This is broken!"
ASR: [FRUSTRATED] "This is broken!"
Brain: <EMPATHETIC> "Oh no... I'm so sorry. Let me fix this right away."
TTS: [empathetic voice] "Oh no... I'm so sorry. Let me fix this right away."
User: 😌 (feels understood)
```

---

## Summary

The Emotional Metadata Bridge ensures that:

1. ✅ **User emotion is preserved** from audio → text
2. ✅ **Response is emotionally appropriate** to context
3. ✅ **Voice tone matches the words** being spoken
4. ✅ **The AI feels human** and empathetic

This is the key to crossing the uncanny valley in voice AI.
