#!/usr/bin/env python3
"""
Parakeet ASR Client (Riva gRPC)
Replaces Qwen2.5-Omni for reliable speech recognition
"""

import io
import wave
import riva.client
import riva.client.proto.riva_asr_pb2 as riva_asr
import riva.client.proto.riva_asr_pb2_grpc as riva_asr_grpc

class ParakeetASRClient:
    """Riva-compatible client for Parakeet ASR"""
    
    def __init__(self, server_address: str = "localhost:50051"):
        self.server_address = server_address
        self.auth = riva.client.Auth(uri=server_address)
        self.asr_service = riva.client.ASRService(self.auth)
        
    def transcribe_pcm(self, pcm_16k: bytes) -> str:
        """
        Transcribe 16kHz PCM audio to text.
        
        Args:
            pcm_16k: Raw PCM16 audio data at 16000 Hz
            
        Returns:
            Transcription text
        """
        try:
            # Create WAV header for the PCM data
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm_16k)
            
            wav_data = wav_buffer.getvalue()
            
            # Use Riva offline recognition
            config = riva.client.RecognitionConfig(
                encoding=riva.client.AudioEncoding.LINEAR_PCM,
                sample_rate_hertz=16000,
                language_code="en-US",
                max_alternatives=1,
                enable_automatic_punctuation=True,
                verbatim_transcripts=True,
            )
            
            response = self.asr_service.offline_recognize(wav_data, config)
            
            # Extract transcription
            if response and response.results:
                transcripts = []
                for result in response.results:
                    if result.alternatives:
                        transcripts.append(result.alternatives[0].transcript)
                return " ".join(transcripts).strip()
            
            return ""
            
        except Exception as e:
            print(f"Parakeet ASR error: {e}")
            import traceback
            traceback.print_exc()
            return ""
    
    def transcribe_streaming(self, audio_generator):
        """
        Streaming transcription (for future use).
        
        Args:
            audio_generator: Generator yielding audio chunks
            
        Yields:
            Transcription chunks
        """
        # TODO: Implement streaming recognition
        pass
