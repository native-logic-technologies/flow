#!/usr/bin/env python3
"""
MOSS-TTS-Realtime Server with Emotional Voice Caching
OpenAI-compatible /v1/audio/speech endpoint with emotion support

This server uses MOSS-TTS-Realtime for high-quality zero-shot voice cloning
with emotional variation through reference audio caching.
"""

import os
import sys
import io
import time
import base64
import logging
from pathlib import Path
from typing import Optional, Dict, Literal
from dataclasses import dataclass
from contextlib import asynccontextmanager

import numpy as np
import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress verbose transformers logging
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

# ============== Configuration ==============

VOICES_DIR = Path("/home/phil/telephony-stack/voices")
MODEL_PATH = "/home/phil/telephony-stack/models/tts/moss-tts-realtime"

EMOTION_MAP = {
    "neutral": "neutral",
    "empathetic": "empathetic", 
    "cheerful": "cheerful",
    "thinking": "thinking",
    "urgent": "urgent",
    # Alias mappings
    "calm": "neutral",
    "sympathetic": "empathetic",
    "happy": "cheerful",
    "excited": "cheerful",
    "contemplative": "thinking",
    "frustrated": "urgent",
    "angry": "urgent",
}

# ============== Voice Cache ==============

@dataclass
class VoiceCache:
    """Cached reference audio for a specific emotion."""
    emotion: str
    audio: torch.Tensor  # Reference audio waveform
    sample_rate: int
    cached_at: float
    
class EmotionalVoiceManager:
    """Manages multiple voice references for different emotions."""
    
    def __init__(self, voices_dir: Path):
        self.voices_dir = voices_dir
        self.caches: Dict[str, VoiceCache] = {}
        self.default_emotion = "neutral"
        self._load_default_voices()
        
    def _load_default_voices(self):
        """Load voice samples from disk."""
        for emotion in ["neutral", "empathetic", "cheerful", "thinking", "urgent"]:
            voice_path = self.voices_dir / emotion / "reference.wav"
            
            if voice_path.exists():
                try:
                    audio, sr = torchaudio.load(str(voice_path))
                    self.caches[emotion] = VoiceCache(
                        emotion=emotion,
                        audio=audio,
                        sample_rate=sr,
                        cached_at=time.time()
                    )
                    logger.info(f"✅ Loaded {emotion} voice from {voice_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to load {emotion} voice: {e}")
            else:
                logger.info(f"ℹ️ No voice sample for '{emotion}' at {voice_path}")
                
    def get_reference_audio(self, emotion: str) -> Optional[torch.Tensor]:
        """Get reference audio for an emotion."""
        # Normalize emotion name
        emotion = EMOTION_MAP.get(emotion.lower(), emotion.lower())
        
        if emotion in self.caches:
            return self.caches[emotion].audio
        
        # Fall back to neutral
        if self.default_emotion in self.caches:
            logger.info(f"Using neutral voice (no cache for '{emotion}')")
            return self.caches[self.default_emotion].audio
            
        return None
    
    def add_voice_sample(self, emotion: str, audio_path: Path) -> bool:
        """Add a new voice sample for an emotion."""
        try:
            audio, sr = torchaudio.load(str(audio_path))
            self.caches[emotion] = VoiceCache(
                emotion=emotion,
                audio=audio,
                sample_rate=sr,
                cached_at=time.time()
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add voice sample: {e}")
            return False

# ============== TTS Pipeline ==============

class MossTTSRealtimePipeline:
    """MOSS-TTS-Realtime inference pipeline."""
    
    def __init__(self, model_path: str, voice_manager: EmotionalVoiceManager):
        self.model_path = model_path
        self.voice_manager = voice_manager
        self.model = None
        self.processor = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
    def load(self):
        """Load the MOSS-TTS-Realtime model."""
        logger.info(f"Loading MOSS-TTS-Realtime from {self.model_path}...")
        logger.info(f"Device: {self.device}")
        
        try:
            from transformers import AutoModelForCausalLM, AutoProcessor
            
            # Load processor
            self.processor = AutoProcessor.from_pretrained(self.model_path, trust_remote_code=True)
            
            # Load model
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
                device_map="auto" if self.device == "cuda" else None,
                trust_remote_code=True
            )
            
            if self.device == "cpu":
                self.model = self.model.to("cpu")
                
            self.model.eval()
            
            logger.info("✅ MOSS-TTS-Realtime loaded successfully!")
            
        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")
            raise
            
    @torch.inference_mode()
    def generate(
        self, 
        text: str, 
        emotion: str = "neutral",
        speed: float = 1.0,
        max_new_tokens: int = 2000
    ) -> np.ndarray:
        """
        Generate speech from text with emotional tone.
        
        Args:
            text: Text to synthesize
            emotion: Emotional tone (neutral, empathetic, cheerful, thinking, urgent)
            speed: Speaking speed multiplier
            max_new_tokens: Maximum tokens to generate
            
        Returns:
            Audio waveform as numpy array (24kHz, float32)
        """
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
            
        # Get reference audio for emotion
        ref_audio = self.voice_manager.get_reference_audio(emotion)
        
        # Prepare inputs
        if ref_audio is not None:
            # Use reference audio for voice cloning
            inputs = self.processor(
                text=text,
                audio=ref_audio.squeeze().numpy(),
                sampling_rate=24000,
                return_tensors="pt"
            )
        else:
            # Text-only generation (no voice cloning)
            inputs = self.processor(
                text=text,
                return_tensors="pt"
            )
            
        # Move to device
        inputs = {k: v.to(self.device) if isinstance(v, torch.Tensor) else v 
                  for k, v in inputs.items()}
        
        # Generate
        start_time = time.time()
        
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=0.8,
            top_p=0.95,
        )
        
        generation_time = time.time() - start_time
        
        # Decode audio
        audio_output = outputs[0].cpu().numpy()
        
        # Resample if speed adjustment requested
        if speed != 1.0:
            audio_output = self._adjust_speed(audio_output, speed)
            
        logger.info(f"Generated {len(audio_output)} samples in {generation_time:.2f}s "
                   f"({len(audio_output)/24000:.2f}s audio)")
        
        return audio_output
        
    def _adjust_speed(self, audio: np.ndarray, speed: float) -> np.ndarray:
        """Adjust audio speed using resampling."""
        if speed == 1.0:
            return audio
            
        # Resample to adjust speed
        import torchaudio.functional as F
        
        tensor = torch.from_numpy(audio).unsqueeze(0)
        # Higher sample rate = faster playback
        new_rate = int(24000 * speed)
        resampled = F.resample(tensor, 24000, new_rate)
        # Resample back to 24kHz
        final = F.resample(resampled, new_rate, 24000)
        
        return final.squeeze().numpy()

# ============== FastAPI Application ==============

class TTSRequest(BaseModel):
    """OpenAI-compatible TTS request."""
    input: str = Field(..., description="Text to synthesize")
    model: Optional[str] = Field("moss-tts-realtime", description="Model ID")
    voice: Optional[str] = Field("neutral", description="Voice/emotion to use")
    response_format: Optional[str] = Field("pcm", description="Audio format")
    speed: Optional[float] = Field(1.0, ge=0.5, le=2.0, description="Speaking speed")
    
    # MOSS-TTS specific
    emotion: Optional[str] = Field(None, description="Emotional tone (neutral, empathetic, cheerful, thinking, urgent)")
    
class TTSResponse(BaseModel):
    """TTS generation metadata."""
    status: str
    emotion: str
    audio_samples: int
    sample_rate: int
    duration_seconds: float
    generation_time_seconds: float

# Global instances
voice_manager: Optional[EmotionalVoiceManager] = None
pipeline: Optional[MossTTSRealtimePipeline] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global voice_manager, pipeline
    
    logger.info("🚀 Starting MOSS-TTS-Realtime Server...")
    
    # Initialize voice manager
    voice_manager = EmotionalVoiceManager(VOICES_DIR)
    
    # Initialize TTS pipeline
    pipeline = MossTTSRealtimePipeline(MODEL_PATH, voice_manager)
    pipeline.load()
    
    logger.info("✅ Server ready!")
    yield
    
    # Cleanup
    logger.info("🛑 Shutting down...")
    if pipeline:
        del pipeline
    torch.cuda.empty_cache()

app = FastAPI(
    title="MOSS-TTS-Realtime Server",
    description="High-quality emotional TTS with zero-shot voice cloning",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health():
    """Health check endpoint."""
    emotions = list(voice_manager.caches.keys()) if voice_manager else []
    return {
        "status": "healthy",
        "model": "MOSS-TTS-Realtime",
        "device": pipeline.device if pipeline else "unknown",
        "available_emotions": emotions,
        "loaded_voices": len(emotions)
    }

@app.get("/voices")
async def list_voices():
    """List available voice emotions."""
    return {
        "voices": [
            {"id": "neutral", "name": "Neutral", "description": "Calm, balanced tone"},
            {"id": "empathetic", "name": "Empathetic", "description": "Soft, caring, understanding"},
            {"id": "cheerful", "name": "Cheerful", "description": "Happy, upbeat, positive"},
            {"id": "thinking", "name": "Thinking", "description": "Contemplative, measured"},
            {"id": "urgent", "name": "Urgent", "description": "Serious, focused, important"},
        ],
        "loaded": list(voice_manager.caches.keys()) if voice_manager else []
    }

@app.post("/v1/audio/speech")
async def create_speech(request: TTSRequest):
    """
    OpenAI-compatible TTS endpoint.
    
    Supports emotional voice cloning via the 'voice' or 'emotion' parameter.
    """
    if not pipeline:
        raise HTTPException(status_code=503, detail="TTS pipeline not initialized")
    
    try:
        # Determine emotion (voice parameter maps to emotion)
        emotion = request.emotion or request.voice or "neutral"
        
        logger.info(f"🎙️ TTS request: '{request.input[:50]}...' emotion={emotion}")
        
        # Generate audio
        start_time = time.time()
        audio = pipeline.generate(
            text=request.input,
            emotion=emotion,
            speed=request.speed
        )
        gen_time = time.time() - start_time
        
        # Convert to requested format
        if request.response_format == "pcm":
            # 24kHz, 16-bit PCM
            audio_pcm = (audio * 32767).astype(np.int16)
            content = audio_pcm.tobytes()
            media_type = "audio/pcm"
        elif request.response_format == "wav":
            # WAV format
            import wave
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes((audio * 32767).astype(np.int16).tobytes())
            content = wav_buffer.getvalue()
            media_type = "audio/wav"
        else:
            # Default to raw PCM
            audio_pcm = (audio * 32767).astype(np.int16)
            content = audio_pcm.tobytes()
            media_type = "audio/pcm"
        
        logger.info(f"✅ Generated {len(audio)} samples ({len(audio)/24000:.2f}s) in {gen_time:.2f}s")
        
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "X-Sample-Rate": "24000",
                "X-Duration": str(len(audio)/24000),
                "X-Generation-Time": str(gen_time),
                "X-Emotion": emotion
            }
        )
        
    except Exception as e:
        logger.error(f"❌ TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate", response_model=TTSResponse)
async def generate_with_metadata(request: TTSRequest):
    """Generate speech with detailed metadata response."""
    if not pipeline:
        raise HTTPException(status_code=503, detail="TTS pipeline not initialized")
    
    try:
        emotion = request.emotion or request.voice or "neutral"
        
        start_time = time.time()
        audio = pipeline.generate(
            text=request.input,
            emotion=emotion,
            speed=request.speed
        )
        gen_time = time.time() - start_time
        
        return TTSResponse(
            status="success",
            emotion=emotion,
            audio_samples=len(audio),
            sample_rate=24000,
            duration_seconds=len(audio)/24000,
            generation_time_seconds=gen_time
        )
        
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/load-voice")
async def load_voice(emotion: str, audio_path: str):
    """Admin endpoint to load a new voice sample."""
    success = voice_manager.add_voice_sample(emotion, Path(audio_path))
    if success:
        return {"status": "success", "emotion": emotion}
    else:
        raise HTTPException(status_code=400, detail="Failed to load voice sample")

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8002,
        log_level="info"
    )
