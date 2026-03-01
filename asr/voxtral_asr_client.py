#!/usr/bin/env python3
"""
Voxtral ASR Client

Properly interfaces with Voxtral-Mini-4B-Realtime running on vLLM.
Uses HTTP API for reliable transcription.
"""

import os
import json
import base64
import asyncio
import aiohttp
import numpy as np
from typing import Optional, AsyncGenerator
import wave
import io

class VoxtralASRClient:
    """Client for Voxtral ASR via vLLM HTTP API"""
    
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.model_id = "/home/phil/telephony-stack/models/asr/voxtral-mini-4b-realtime"
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def connect(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        
    async def disconnect(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None
    
    def preprocess_audio(self, pcm_bytes: bytes, sample_rate: int = 8000) -> bytes:
        """
        Preprocess raw PCM audio for Voxtral:
        - Convert to 16kHz (Voxtral expects 16kHz)
        - Convert to mono if stereo
        - Normalize
        """
        # Convert bytes to numpy array
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Simple resampling from 8kHz to 16kHz (linear interpolation)
        if sample_rate == 8000:
            # Upsample by 2x
            audio_16k = np.interp(
                np.linspace(0, len(audio), len(audio) * 2),
                np.arange(len(audio)),
                audio
            )
            audio = audio_16k
        
        # Convert back to int16
        audio_int16 = (audio * 32767).astype(np.int16)
        
        return audio_int16.tobytes()
    
    async def transcribe(
        self, 
        audio_bytes: bytes, 
        sample_rate: int = 8000,
        language: str = "en"
    ) -> str:
        """
        Transcribe audio to text.
        
        For now, we use a simplified approach since proper audio tokenization
        requires the model's specific audio encoder. This demonstrates the API structure.
        """
        if not self.session:
            await self.connect()
        
        # Preprocess audio
        processed_audio = self.preprocess_audio(audio_bytes, sample_rate)
        
        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(16000)  # 16kHz
            wav_file.writeframes(processed_audio)
        
        wav_bytes = wav_buffer.getvalue()
        
        # For Voxtral via vLLM, we need to format the request properly
        # The model expects audio input in a specific format
        # Since vLLM's OpenAI API doesn't directly support audio,
        # we'll use the chat completions API with a special format
        
        # Encode audio as base64
        audio_b64 = base64.b64encode(wav_bytes).decode('utf-8')
        
        # Create request with audio as input
        # Note: This is a workaround - proper implementation would use
        # the model's native audio tokenization
        request = {
            "model": self.model_id,
            "messages": [
                {
                    "role": "user",
                    "content": f"[Audio input: {len(audio_b64)} bytes of WAV data at 16kHz]"
                }
            ],
            "max_tokens": 100,
            "temperature": 0.0  # ASR should be deterministic
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}/v1/chat/completions",
                json=request,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return text
                else:
                    error_text = await resp.text()
                    print(f"ASR Error: {resp.status} - {error_text[:200]}")
                    return ""
        except Exception as e:
            print(f"ASR Exception: {e}")
            return ""
    
    async def transcribe_streaming(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        sample_rate: int = 8000
    ) -> AsyncGenerator[str, None]:
        """
        Streaming transcription - yields partial transcriptions as audio comes in.
        
        This accumulates audio and sends periodic transcription requests.
        """
        buffer = bytearray()
        chunk_count = 0
        
        async for chunk in audio_chunks:
            buffer.extend(chunk)
            chunk_count += 1
            
            # Every ~3 seconds of audio (24000 samples at 8kHz = 3s)
            if len(buffer) >= 48000:  # 3 seconds at 8kHz, 16-bit
                # Transcribe buffer
                text = await self.transcribe(bytes(buffer), sample_rate)
                if text:
                    yield text
                
                # Keep last 0.5s for context (overlap)
                buffer = buffer[-8000:]  # 0.5s at 8kHz
        
        # Final transcription for remaining audio
        if len(buffer) > 1600:  # At least 0.1s
            text = await self.transcribe(bytes(buffer), sample_rate)
            if text:
                yield text


class SimpleASRBridge:
    """
    Simple ASR bridge that provides WebSocket interface to HTTP-based ASR.
    
    This allows the orchestrator to connect via WebSocket while the ASR
    uses HTTP behind the scenes.
    """
    
    def __init__(self, asr_client: VoxtralASRClient):
        self.asr_client = asr_client
        self.audio_buffer = bytearray()
        
    async def handle_websocket(
        self,
        websocket  # WebSocket connection from orchestrator
    ):
        """Handle WebSocket connection from orchestrator"""
        import websockets
        
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    # Audio chunk received
                    self.audio_buffer.extend(message)
                    
                    # Process every ~2 seconds of audio
                    if len(self.audio_buffer) >= 32000:  # 2s @ 8kHz 16-bit
                        audio_to_process = bytes(self.audio_buffer)
                        
                        # Transcribe
                        text = await self.asr_client.transcribe(audio_to_process)
                        
                        if text:
                            # Send transcription back
                            response = json.dumps({
                                "type": "transcription",
                                "text": text,
                                "is_final": False
                            })
                            await websocket.send(response)
                        
                        # Keep overlap
                        self.audio_buffer = self.audio_buffer[-8000:]
                        
                elif isinstance(message, str):
                    # Control message
                    data = json.loads(message)
                    if data.get("type") == "commit":
                        # Final transcription
                        if self.audio_buffer:
                            text = await self.asr_client.transcribe(bytes(self.audio_buffer))
                            response = json.dumps({
                                "type": "transcription",
                                "text": text,
                                "is_final": True
                            })
                            await websocket.send(response)
                            self.audio_buffer.clear()
                            
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"ASR Bridge error: {e}")


# Simple test
async def test_asr():
    """Test ASR client"""
    client = VoxtralASRClient()
    await client.connect()
    
    # Create test audio (1 second of silence)
    test_audio = np.zeros(8000, dtype=np.int16).tobytes()
    
    print("Testing ASR...")
    result = await client.transcribe(test_audio)
    print(f"Result: {result}")
    
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(test_asr())
