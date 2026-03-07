#!/usr/bin/env python3
"""
Whisper ASR Fallback
Uses transformers Whisper when Parakeet is unavailable
"""

import os
os.environ['HF_HOME'] = '/tmp/hf_cache'

import io
import torch
import numpy as np
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

class WhisperASR:
    """Fallback ASR using Whisper base model"""
    
    def __init__(self):
        self.pipe = None
        self.device = None
        
    def load(self):
        """Load Whisper model (call once on startup)"""
        if self.pipe is not None:
            return
            
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        
        print(f"🎤 Loading Whisper ASR fallback on {device}...")
        
        model_id = "openai/whisper-base"  # Small and fast
        
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_id,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True
        )
        model.to(device)
        
        processor = AutoProcessor.from_pretrained(model_id)
        
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            torch_dtype=torch_dtype,
            device=device,
        )
        self.device = device
        print(f"✅ Whisper ASR ready on {device}")
        
    def transcribe(self, pcm_16k: bytes) -> str:
        """
        Transcribe 16kHz PCM audio to text.
        
        Args:
            pcm_16k: Raw PCM16 audio data at 16000 Hz (mono)
            
        Returns:
            Transcription text
        """
        if self.pipe is None:
            self.load()
            
        try:
            # Convert PCM bytes to numpy array
            audio_np = np.frombuffer(pcm_16k, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Transcribe
            result = self.pipe(
                audio_np,
                chunk_length_s=30,
                batch_size=1,
                return_timestamps=False,
            )
            
            return result.get("text", "").strip()
            
        except Exception as e:
            print(f"Whisper ASR error: {e}")
            return ""

# Global instance
_whisper_asr = None

def get_whisper_asr():
    """Get or create global Whisper ASR instance"""
    global _whisper_asr
    if _whisper_asr is None:
        _whisper_asr = WhisperASR()
        _whisper_asr.load()
    return _whisper_asr
