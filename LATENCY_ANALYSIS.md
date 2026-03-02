# Latency Analysis - Why We're Not at 500ms

## Current Measured Latencies

| Component | Measured | Target | Gap |
|-----------|----------|--------|-----|
| **WebSocket Connect** | 15ms | - | ✅ Good |
| **LLM TTFT** | 250ms | 60ms | ⚠️ 4x slower |
| **LLM Full Response** | 1000-2000ms | - | Acceptable |
| **TTS First Byte** | 2145ms | 200ms | ❌ 10x slower |
| **Total E2E** | 2200-4000ms | 500ms | ❌ 5-8x slower |

## Root Cause: MOSS-TTS Architecture

**MOSS-TTS-Realtime** is not actually "realtime" for first-chunk latency. It:

1. Processes the full text input
2. Generates audio frames in batches
3. Only yields chunks after significant processing
4. **First chunk takes 2000+ ms**

This is a fundamental limitation of the MOSS-TTS model architecture - it's optimized for throughput, not low-latency first-chunk.

## Attempted Optimizations

### ✅ What Helped:
- Sentence-level streaming (reduced 4000ms → 2200ms)
- Removed AGC (clean audio, no distortion)
- Smaller TTS chunks (6 vs 12)

### ❌ What Didn't:
- `/nothink` prompt (model still "thinks")
- `bad_words` array (model ignores it)
- Chunk size reduction (MOSS still buffers)

## Realistic Options

### Option 1: Accept 2-3s Latency
- Document that S2S has 2-3s latency
- Focus on audio quality (which is excellent)
- Use for async/non-real-time use cases

### Option 2: Switch to True Low-Latency TTS
Replace MOSS-TTS with:
- **StyleTTS 2** (~100ms first chunk)
- **Coqui TTS** (~200ms first chunk)
- **Microsoft Azure TTS** (~150ms first chunk)
- **Amazon Polly** (~100ms first chunk)

### Option 3: Hybrid Approach
- Use MOSS-TTS for high-quality final output
- Use fast TTS (StyleTTS) for first sentence
- Switch to MOSS after initial response

### Option 4: Pre-generate Common Phrases
- Cache TTS for: "Hey there!", "Mmm hmm", "Let me think..."
- Play cached audio instantly while MOSS generates

## Recommendation

For a production voice assistant with <500ms latency:

**Replace MOSS-TTS with StyleTTS 2 or Coqui TTS.**

MOSS-TTS is excellent quality but fundamentally wrong architecture for real-time S2S.
