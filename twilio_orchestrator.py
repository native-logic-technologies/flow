#!/usr/bin/env python3
"""
Native Logic Telephony Orchestrator
Real-time Twilio integration with Qwen2.5-Omni native diarization

Features:
- Multi-speaker diarization via Qwen2.5-Omni (no separate model needed!)
- 8kHz μ-law → 16kHz PCM conversion
- Sub-500ms end-to-end latency
- Conversational memory per call
- Sesame-level voice cloning via MOSS-TTS
"""

import asyncio
import base64
import json
import io
import wave
import audioop
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
from datetime import datetime

import numpy as np
import websockets
from websockets.server import serve
import aiohttp
import torch
import torchaudio

# Configuration
BRAIN_URL = "http://localhost:8000/v1/chat/completions"
EAR_URL = "http://localhost:8001/v1/chat/completions"
VOICE_URL = "http://localhost:8002/v1/audio/speech"

# Audio settings
TWILIO_RATE = 8000  # 8kHz from Twilio
TARGET_RATE = 16000  # 16kHz for Omni model
CHUNK_DURATION_MS = 100  # 100ms chunks for low latency
BYTES_PER_SAMPLE = 2  # 16-bit PCM

# Latency targets
TARGET_LATENCY_MS = 500
MAX_RESPONSE_TOKENS = 80  # Keep responses short for telephony


@dataclass
class Speaker:
    """Represents a speaker in the conversation."""
    speaker_id: str  # "speaker_1", "speaker_2", etc.
    first_seen: datetime
    last_seen: datetime
    utterance_count: int = 0
    voice_profile: Optional[np.ndarray] = None  # For voice adaptation
    
    def to_context(self) -> str:
        """Generate context string for this speaker."""
        return f"{self.speaker_id} (active since {self.first_seen.strftime('%H:%M:%S')}, {self.utterance_count} utterances)"


@dataclass
class ConversationTurn:
    """A single turn in the conversation."""
    timestamp: datetime
    speaker_id: str
    text: str
    emotion: Optional[str] = None
    audio_duration_ms: float = 0.0


@dataclass
class CallSession:
    """Manages state for a single phone call."""
    call_sid: str
    created_at: datetime = field(default_factory=datetime.now)
    
    # Speaker tracking (native diarization via Omni)
    speakers: Dict[str, Speaker] = field(default_factory=dict)
    current_speaker: Optional[str] = None
    speaker_counter: int = 0
    
    # Conversation history
    history: deque = field(default_factory=lambda: deque(maxlen=20))
    system_prompt: str = """You are Phil, a helpful AI assistant on a phone call. 
Be warm, conversational, and natural. Use verbal fillers ("um", "ah") occasionally.
Keep responses brief (1-2 sentences) for phone conversations.
You can identify different speakers in the conversation."""
    
    # Audio buffering
    audio_buffer: bytearray = field(default_factory=bytearray)
    last_utterance_time: Optional[datetime] = None
    silence_duration_ms: float = 0.0
    
    # Performance tracking
    total_turns: int = 0
    avg_latency_ms: float = 0.0
    
    def get_or_create_speaker(self, speaker_hint: Optional[str] = None) -> Speaker:
        """Get existing speaker or create new one based on Omni's diarization."""
        if speaker_hint and speaker_hint in self.speakers:
            return self.speakers[speaker_hint]
        
        # Create new speaker
        self.speaker_counter += 1
        speaker_id = f"speaker_{self.speaker_counter}"
        now = datetime.now()
        speaker = Speaker(
            speaker_id=speaker_id,
            first_seen=now,
            last_seen=now
        )
        self.speakers[speaker_id] = speaker
        self.current_speaker = speaker_id
        return speaker
    
    def add_turn(self, speaker_id: str, text: str, emotion: Optional[str] = None):
        """Add a conversation turn to history."""
        turn = ConversationTurn(
            timestamp=datetime.now(),
            speaker_id=speaker_id,
            text=text,
            emotion=emotion
        )
        self.history.append(turn)
        
        if speaker_id in self.speakers:
            self.speakers[speaker_id].utterance_count += 1
            self.speakers[speaker_id].last_seen = datetime.now()
        
        self.total_turns += 1
    
    def get_history_for_llm(self, max_turns: int = 10) -> list:
        """Format history for LLM context."""
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # Add speaker context if multiple speakers detected
        if len(self.speakers) > 1:
            speaker_context = "Multiple speakers detected:\n" + \
                "\n".join([s.to_context() for s in self.speakers.values()])
            messages.append({"role": "system", "content": speaker_context})
        
        # Add conversation history
        for turn in list(self.history)[-max_turns:]:
            prefix = f"[{turn.speaker_id}] " if len(self.speakers) > 1 else ""
            emotion_suffix = f" (emotion: {turn.emotion})" if turn.emotion else ""
            
            if turn.speaker_id.startswith("speaker"):
                # Human speaker
                messages.append({
                    "role": "user", 
                    "content": f"{prefix}{turn.text}{emotion_suffix}"
                })
            else:
                # AI (Phil)
                messages.append({"role": "assistant", "content": turn.text})
        
        return messages


class AudioProcessor:
    """Handles audio format conversions."""
    
    @staticmethod
    def ulaw_to_pcm(ulaw_data: bytes) -> bytes:
        """Convert μ-law to 16-bit PCM."""
        return audioop.ulaw2lin(ulaw_data, 2)
    
    @staticmethod
    def pcm_to_ulaw(pcm_data: bytes) -> bytes:
        """Convert 16-bit PCM to μ-law."""
        return audioop.lin2ulaw(pcm_data, 2)
    
    @staticmethod
    def resample_8k_to_16k(pcm_8k: bytes) -> bytes:
        """Resample 8kHz PCM to 16kHz."""
        return audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)[0]
    
    @staticmethod
    def resample_16k_to_8k(pcm_16k: bytes) -> bytes:
        """Resample 16kHz PCM to 8kHz."""
        return audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)[0]
    
    @staticmethod
    def bytes_to_numpy(pcm_bytes: bytes) -> np.ndarray:
        """Convert PCM bytes to numpy array."""
        return np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    
    @staticmethod
    def numpy_to_bytes(audio_array: np.ndarray) -> bytes:
        """Convert numpy array to PCM bytes."""
        audio_int16 = (audio_array * 32767).astype(np.int16)
        return audio_int16.tobytes()


class TwilioOrchestrator:
    """Main orchestrator for Twilio telephony integration."""
    
    def __init__(self):
        self.sessions: Dict[str, CallSession] = {}
        self.audio_processor = AudioProcessor()
        self.http_session: Optional[aiohttp.ClientSession] = None
        
        # Latency optimization: Pre-allocate buffers
        self._audio_chunk_buffer = bytearray()
        
    async def start(self):
        """Start the orchestrator."""
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"Content-Type": "application/json"}
        )
        print("🚀 Telephony Orchestrator started")
        print(f"   Brain: {BRAIN_URL}")
        print(f"   Ear: {EAR_URL}")
        print(f"   Voice: {VOICE_URL}")
    
    async def stop(self):
        """Stop the orchestrator."""
        if self.http_session:
            await self.http_session.close()
    
    def get_or_create_session(self, call_sid: str) -> CallSession:
        """Get existing session or create new one."""
        if call_sid not in self.sessions:
            self.sessions[call_sid] = CallSession(call_sid=call_sid)
            print(f"📞 New call session: {call_sid}")
        return self.sessions[call_sid]
    
    async def process_audio_chunk(self, call_sid: str, ulaw_chunk: bytes) -> Optional[dict]:
        """
        Process incoming audio from Twilio.
        Returns response dict when a complete utterance is detected.
        """
        session = self.get_or_create_session(call_sid)
        
        # Convert μ-law to PCM
        pcm_8k = self.audio_processor.ulaw_to_pcm(ulaw_chunk)
        
        # Resample to 16kHz for Omni model
        pcm_16k = self.audio_processor.resample_8k_to_16k(pcm_8k)
        
        # Add to buffer
        session.audio_buffer.extend(pcm_16k)
        
        # Check for silence (simple energy-based detection)
        audio_array = self.audio_processor.bytes_to_numpy(pcm_16k)
        energy = np.abs(audio_array).mean()
        
        SILENCE_THRESHOLD = 0.01  # Adjust based on testing
        MIN_UTTERANCE_MS = 500    # Minimum 500ms to process
        MAX_UTTERANCE_MS = 10000  # Maximum 10 seconds
        
        buffer_duration_ms = len(session.audio_buffer) / (TARGET_RATE * BYTES_PER_SAMPLE) * 1000
        
        if energy < SILENCE_THRESHOLD:
            session.silence_duration_ms += CHUNK_DURATION_MS
        else:
            session.silence_duration_ms = 0
        
        # Process when we have enough audio followed by silence
        should_process = (
            buffer_duration_ms >= MIN_UTTERANCE_MS and 
            session.silence_duration_ms > 300  # 300ms silence
        ) or buffer_duration_ms >= MAX_UTTERANCE_MS
        
        if should_process and len(session.audio_buffer) > 0:
            # Process the utterance
            result = await self._process_utterance(call_sid, bytes(session.audio_buffer))
            session.audio_buffer = bytearray()  # Clear buffer
            session.silence_duration_ms = 0
            return result
        
        return None
    
    async def _process_utterance(self, call_sid: str, pcm_16k: bytes) -> Optional[dict]:
        """
        Process a complete utterance through the AI stack.
        
        Pipeline:
        1. EAR (Port 8001): Diarization + Transcription + Emotion
        2. BRAIN (Port 8000): Generate response
        3. VOICE (Port 8002): Synthesize speech
        """
        session = self.get_or_create_session(call_sid)
        start_time = time.time()
        
        try:
            # === STEP 1: EAR - Native Diarization + Transcription + Emotion ===
            print(f"👂 Processing utterance for {call_sid[:20]}...")
            
            # Convert to WAV for Omni model
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(TARGET_RATE)
                wav_file.writeframes(pcm_16k)
            
            audio_base64 = base64.b64encode(wav_buffer.getvalue()).decode('utf-8')
            
            # Query Omni model for diarization + transcription + emotion
            ear_payload = {
                "model": "Qwen/Qwen2.5-Omni-7B",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text", 
                                "text": "Identify the speaker, transcribe exactly what they said, and describe their emotion/tone. Format: [Speaker X]: \"transcription\" (emotion)"
                            },
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": audio_base64,
                                    "format": "wav"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 150,
                "temperature": 0.0  # Deterministic for accuracy
            }
            
            async with self.http_session.post(EAR_URL, json=ear_payload) as resp:
                if resp.status != 200:
                    print(f"❌ Ear error: {resp.status}")
                    return None
                
                ear_result = await resp.json()
                ear_content = ear_result['choices'][0]['message']['content']
            
            print(f"   📝 Ear output: {ear_content[:100]}...")
            
            # Parse speaker identification from Ear output
            # Expected format: [Speaker 1]: "text" (emotion) or variations
            speaker_id = self._parse_speaker_from_ear(ear_content, session)
            emotion = self._parse_emotion_from_ear(ear_content)
            transcription = self._parse_transcription_from_ear(ear_content)
            
            # Add to conversation history
            session.add_turn(speaker_id, transcription, emotion)
            
            # === STEP 2: BRAIN - Generate Response ===
            print(f"🧠 Generating response...")
            
            messages = session.get_history_for_llm()
            
            # Add emotion awareness to context
            if emotion:
                messages.append({
                    "role": "system",
                    "content": f"The user sounds {emotion}. Respond with appropriate empathy."
                })
            
            brain_payload = {
                "model": "/home/phil/telephony-stack/models/qwen2.5-vl-fp8",
                "messages": messages,
                "max_tokens": MAX_RESPONSE_TOKENS,
                "temperature": 0.7,
                "stream": False  # Synchronous for telephony
            }
            
            async with self.http_session.post(BRAIN_URL, json=brain_payload) as resp:
                if resp.status != 200:
                    print(f"❌ Brain error: {resp.status}")
                    return None
                
                brain_result = await resp.json()
                response_text = brain_result['choices'][0]['message']['content']
            
            print(f"   💬 Brain response: {response_text[:100]}...")
            
            # Add AI response to history
            session.add_turn("assistant", response_text)
            
            # === STEP 3: VOICE - Synthesize Speech ===
            print(f"🗣️ Synthesizing voice...")
            
            voice_payload = {
                "input": response_text,
                "voice": "phil-conversational",
                "speed": 1.0,
                "response_format": "wav"
            }
            
            async with self.http_session.post(VOICE_URL, json=voice_payload) as resp:
                if resp.status != 200:
                    print(f"❌ Voice error: {resp.status}")
                    return None
                
                voice_audio = await resp.read()
            
            # Convert voice output (24kHz) to 8kHz μ-law for Twilio
            response_pcm = self._convert_voice_to_twilio(voice_audio)
            
            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            session.avg_latency_ms = (session.avg_latency_ms * (session.total_turns - 1) + latency_ms) / session.total_turns
            
            print(f"   ✅ Latency: {latency_ms:.0f}ms (avg: {session.avg_latency_ms:.0f}ms)")
            
            return {
                "type": "response",
                "speaker_id": speaker_id,
                "transcription": transcription,
                "emotion": emotion,
                "response_text": response_text,
                "audio_ulaw": base64.b64encode(response_pcm).decode('utf-8'),
                "latency_ms": latency_ms
            }
            
        except Exception as e:
            print(f"❌ Error processing utterance: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _parse_speaker_from_ear(self, ear_output: str, session: CallSession) -> str:
        """Parse speaker ID from Ear output."""
        # Try to extract [Speaker X] pattern
        import re
        match = re.search(r'\[?Speaker\s*(\d+)\]?', ear_output, re.IGNORECASE)
        if match:
            speaker_num = match.group(1)
            speaker_id = f"speaker_{speaker_num}"
            # Ensure speaker exists
            if speaker_id not in session.speakers:
                session.get_or_create_speaker(speaker_id)
            return speaker_id
        
        # Default to current or create new
        if session.current_speaker:
            return session.current_speaker
        return session.get_or_create_speaker().speaker_id
    
    def _parse_emotion_from_ear(self, ear_output: str) -> Optional[str]:
        """Parse emotion from Ear output."""
        import re
        # Look for emotion in parentheses
        match = re.search(r'\(([^)]+)\)', ear_output)
        if match:
            emotion = match.group(1).lower()
            # Filter for emotion keywords
            emotion_keywords = ['happy', 'sad', 'angry', 'frustrated', 'excited', 
                              'calm', 'neutral', 'concerned', 'urgent', 'confused']
            for keyword in emotion_keywords:
                if keyword in emotion:
                    return keyword
        return None
    
    def _parse_transcription_from_ear(self, ear_output: str) -> str:
        """Extract clean transcription from Ear output."""
        import re
        # Remove speaker tags and emotion markers
        clean = re.sub(r'\[?Speaker\s*\d+\]?:?\s*', '', ear_output, flags=re.IGNORECASE)
        clean = re.sub(r'\([^)]+\)', '', clean)
        clean = clean.strip('"').strip()
        return clean
    
    def _convert_voice_to_twilio(self, wav_data: bytes) -> bytes:
        """Convert MOSS-TTS output (24kHz) to Twilio format (8kHz μ-law)."""
        # Read WAV
        wav_buffer = io.BytesIO(wav_data)
        with wave.open(wav_buffer, 'rb') as wav_file:
            n_channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            framerate = wav_file.getframerate()
            n_frames = wav_file.getnframes()
            pcm_data = wav_file.readframes(n_frames)
        
        # Convert stereo to mono if needed
        if n_channels == 2:
            pcm_data = audioop.tomono(pcm_data, sample_width, 1, 1)
        
        # Resample 24kHz → 16kHz → 8kHz (better quality than direct 24k→8k)
        pcm_16k = audioop.ratecv(pcm_data, sample_width, 1, framerate, 16000, None)[0]
        pcm_8k = audioop.ratecv(pcm_16k, sample_width, 1, 16000, 8000, None)[0]
        
        # Convert to μ-law
        ulaw_data = audioop.lin2ulaw(pcm_8k, sample_width)
        
        return ulaw_data
    
    async def handle_twilio_ws(self, websocket, path):
        """Handle WebSocket connection from Twilio."""
        call_sid = None
        print(f"🔌 New Twilio WebSocket connection: {path}")
        
        try:
            async for message in websocket:
                data = json.loads(message)
                
                # Handle Twilio Media messages
                if data.get('event') == 'start':
                    call_sid = data['start']['callSid']
                    stream_sid = data['start']['streamSid']
                    print(f"📞 Call started: {call_sid}, Stream: {stream_sid}")
                    
                    # Send greeting
                    await self._send_greeting(websocket, call_sid)
                    
                elif data.get('event') == 'media':
                    if not call_sid:
                        continue
                    
                    # Decode μ-law audio from Twilio
                    ulaw_chunk = base64.b64decode(data['media']['payload'])
                    
                    # Process audio
                    result = await self.process_audio_chunk(call_sid, ulaw_chunk)
                    
                    if result:
                        # Send response back to Twilio
                        await self._send_audio_response(websocket, result['audio_ulaw'])
                        
                elif data.get('event') == 'stop':
                    print(f"📴 Call ended: {call_sid}")
                    if call_sid in self.sessions:
                        session = self.sessions[call_sid]
                        print(f"   📊 Stats: {session.total_turns} turns, "
                              f"avg latency: {session.avg_latency_ms:.0f}ms")
                        del self.sessions[call_sid]
                    break
                    
        except websockets.exceptions.ConnectionClosed:
            print(f"🔌 Connection closed: {call_sid}")
            if call_sid and call_sid in self.sessions:
                del self.sessions[call_sid]
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _send_greeting(self, websocket, call_sid: str):
        """Send initial greeting to caller."""
        greeting = "Hello, this is Phil from Native Logic. How can I help you today?"
        
        # Synthesize greeting
        voice_payload = {
            "input": greeting,
            "voice": "phil-conversational",
            "speed": 1.0,
            "response_format": "wav"
        }
        
        try:
            async with self.http_session.post(VOICE_URL, json=voice_payload) as resp:
                if resp.status == 200:
                    voice_audio = await resp.read()
                    response_pcm = self._convert_voice_to_twilio(voice_audio)
                    await self._send_audio_response(
                        websocket, 
                        base64.b64encode(response_pcm).decode('utf-8')
                    )
                    # Add to session history
                    session = self.get_or_create_session(call_sid)
                    session.add_turn("assistant", greeting)
        except Exception as e:
            print(f"❌ Failed to send greeting: {e}")
    
    async def _send_audio_response(self, websocket, audio_base64: str):
        """Send audio response back to Twilio."""
        # Twilio expects μ-law audio
        message = {
            "event": "media",
            "streamSid": "todo_get_stream_sid",  # Need to track this
            "media": {
                "payload": audio_base64
            }
        }
        await websocket.send(json.dumps(message))


async def main():
    """Main entry point."""
    orchestrator = TwilioOrchestrator()
    await orchestrator.start()
    
    # Start WebSocket server for Twilio
    print("🔌 Starting WebSocket server on ws://0.0.0.0:8765")
    
    async with serve(
        orchestrator.handle_twilio_ws,
        "0.0.0.0",
        8765,
        ping_interval=20,
        ping_timeout=10
    ):
        print("✅ Telephony orchestrator ready!")
        print("   WebSocket: ws://localhost:8765/twilio")
        print("   Ready for Twilio Stream connections")
        
        # Keep running
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
