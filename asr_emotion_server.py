#!/usr/bin/env python3
"""
ASR with Emotion Extraction Server
Uses Qwen2.5-Omni to transcribe audio and detect emotional state.

Output format: [EMOTION] "transcription"
Emotions: NEUTRAL, FRUSTRATED, JOYFUL, HESITANT, URGENT, CONFUSED
"""

import os
import sys
import io
import base64
import logging
from typing import Optional, Literal
from contextlib import asynccontextmanager

import numpy as np
import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== Configuration ==============

MODEL_PATH = "/home/phil/telephony-stack/models/asr/qwen2.5-omni"  # Qwen 2.5 Omni for ASR

EMOTION_PROMPT = """<|im_start|>system
You are an emotion-aware speech recognition system. 
Analyze the audio and transcribe the speech.
Prefix the transcription with the speaker's emotional state using one of these tags:
[NEUTRAL] - Normal, calm speech
[FRUSTRATED] - Annoyed, angry, or upset tone
[JOYFUL] - Happy, excited, cheerful tone  
[HESITANT] - Uncertain, pausing, thinking tone
[URGENT] - Rushed, important, stressed tone
[CONFUSED] - Unclear, questioning, lost tone

Respond ONLY with the emotion tag followed by the transcription.<|im_end|>
<|im_start|>user
<|audio_placeholder|><|im_end|>
<|im_start|>assistant
"""

# ============== ASR Pipeline ==============

class EmotionAwareASR:
    """Qwen2.5-Omni based ASR with emotion detection."""
    
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = None
        self.processor = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
    def load(self):
        """Load the Qwen2.5-Omni model."""
        logger.info(f"Loading Qwen2.5-Omni from {self.model_path}...")
        
        try:
            from transformers import Qwen2_5OmniModel, Qwen2_5OmniProcessor
            
            self.processor = Qwen2_5OmniProcessor.from_pretrained(self.model_path)
            self.model = Qwen2_5OmniModel.from_pretrained(
                self.model_path,
                torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
                device_map="auto" if self.device == "cuda" else None,
            )
            
            if self.device == "cpu":
                self.model = self.model.to("cpu")
                
            self.model.eval()
            logger.info("✅ Qwen2.5-Omni loaded successfully!")
            
        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")
            logger.info("⚠️ Falling back to standard ASR without emotion...")
            self.model = None
            
    @torch.inference_mode()
    def transcribe(
        self, 
        audio: np.ndarray, 
        sample_rate: int = 16000
    ) -> tuple[str, str]:
        """
        Transcribe audio with emotion detection.
        
        Returns:
            (emotion, transcription) tuple
        """
        if self.model is None:
            # Fallback: return neutral with placeholder
            return "NEUTRAL", "Audio transcription placeholder (model not loaded)"
            
        try:
            # Resample to 16kHz if needed
            if sample_rate != 16000:
                audio_tensor = torch.from_numpy(audio).unsqueeze(0)
                audio_tensor = torchaudio.functional.resample(
                    audio_tensor, sample_rate, 16000
                )
                audio = audio_tensor.squeeze().numpy()
            
            # Process audio
            inputs = self.processor(
                text=EMOTION_PROMPT,
                audios=audio,
                sampling_rate=16000,
                return_tensors="pt"
            )
            
            inputs = {k: v.to(self.device) if isinstance(v, torch.Tensor) else v 
                     for k, v in inputs.items()}
            
            # Generate
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
            )
            
            # Decode
            result = self.processor.decode(outputs[0], skip_special_tokens=True)
            
            # Parse emotion and text
            emotion, text = self._parse_emotion(result)
            
            return emotion, text
            
        except Exception as e:
            logger.error(f"ASR failed: {e}")
            return "NEUTRAL", ""
            
    def _parse_emotion(self, text: str) -> tuple[str, str]:
        """Parse emotion tag from model output."""
        text = text.strip()
        
        # Check for emotion tags
        emotions = ["NEUTRAL", "FRUSTRATED", "JOYFUL", "HESITANT", "URGENT", "CONFUSED"]
        
        for emotion in emotions:
            tag = f"[{emotion}]"
            if tag in text:
                # Extract text after tag
                parts = text.split(tag, 1)
                if len(parts) > 1:
                    return emotion, parts[1].strip().strip('"')
                return emotion, ""
                
        # No tag found, assume neutral
        return "NEUTRAL", text.strip('"')

# ============== FastAPI Application ==============

class TranscriptionRequest(BaseModel):
    """ASR request with audio."""
    audio: str = Field(..., description="Base64-encoded audio (WAV or raw PCM)")
    format: Optional[str] = Field("wav", description="Audio format: wav, pcm")
    sample_rate: Optional[int] = Field(16000, description="Sample rate if PCM")
    language: Optional[str] = Field("en", description="Language code")

class TranscriptionResponse(BaseModel):
    """ASR response with emotion."""
    text: str = Field(..., description="Transcribed text without emotion tag")
    emotion: str = Field(..., description="Detected emotion")
    full_output: str = Field(..., description="Raw output with emotion tag")
    confidence: Optional[float] = Field(None, description="Confidence score")

# Global instance
asr_pipeline: Optional[EmotionAwareASR] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global asr_pipeline
    
    logger.info("🚀 Starting Emotion-Aware ASR Server...")
    
    asr_pipeline = EmotionAwareASR(MODEL_PATH)
    asr_pipeline.load()
    
    logger.info("✅ ASR Server ready!")
    yield
    
    logger.info("🛑 Shutting down...")
    if asr_pipeline:
        del asr_pipeline
    torch.cuda.empty_cache()

app = FastAPI(
    title="Emotion-Aware ASR Server",
    description="Qwen2.5-Omni based speech recognition with emotion detection",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model": "Qwen2.5-Omni",
        "emotion_detection": asr_pipeline.model is not None,
        "device": asr_pipeline.device if asr_pipeline else "unknown"
    }

@app.post("/v1/audio/transcriptions", response_model=TranscriptionResponse)
async def transcribe(request: TranscriptionRequest):
    """
    Transcribe audio with emotion detection.
    
    Returns the transcription with detected emotion.
    """
    if not asr_pipeline:
        raise HTTPException(status_code=503, detail="ASR not initialized")
    
    try:
        # Decode audio
        audio_bytes = base64.b64decode(request.audio)
        
        if request.format == "wav":
            # Parse WAV
            import wave
            wav = wave.open(io.BytesIO(audio_bytes), 'rb')
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
            sample_rate = wav.getframerate()
            audio = audio.astype(np.float32) / 32768.0
        else:
            # Raw PCM
            audio = np.frombuffer(audio_bytes, dtype=np.int16)
            audio = audio.astype(np.float32) / 32768.0
            sample_rate = request.sample_rate
        
        # Transcribe
        emotion, text = asr_pipeline.transcribe(audio, sample_rate)
        
        logger.info(f"🎤 ASR: [{emotion}] \"{text[:60]}...\"")
        
        return TranscriptionResponse(
            text=text,
            emotion=emotion,
            full_output=f"[{emotion}] \"{text}\"",
            confidence=None  # Could add confidence scoring
        )
        
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transcribe")
async def transcribe_simple(request: TranscriptionRequest):
    """Simple transcription endpoint (alias)."""
    return await transcribe(request)

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )
