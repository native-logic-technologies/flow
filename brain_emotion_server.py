#!/usr/bin/env python3
"""
Brain with Emotional Reasoning Server
Uses Qwen3.5-9B to generate empathetic responses with emotional tone tags.

Output format: <EMOTION> "response text"
Emotions: EMPATHETIC, CHEERFUL, PROFESSIONAL, THINKING, URGENT, NEUTRAL
"""

import os
import sys
import logging
from typing import Optional, List, Dict
from contextlib import asynccontextmanager
from dataclasses import dataclass

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== Configuration ==============

MODEL_PATH = "/home/phil/telephony-stack/models/llm/qwen3.5-9b"  # Qwen 3.5 9B

# Emotional reasoning prompt template
EMOTION_BRAIN_PROMPT = """<|im_start|>system
You are Phil, a helpful and empathetic AI assistant.
Your task is to respond to the user with appropriate emotional intelligence.

When responding, prefix your answer with an emotional tone tag:
<EMPATHETIC> - Use for frustrated, upset, or concerned users (soft, caring tone)
<CHEERFUL> - Use for happy, excited, or positive contexts (upbeat tone)
<PROFESSIONAL> - Use for business, technical, or formal contexts (neutral, clear tone)
<THINKING> - Use when considering, analyzing, or pausing (contemplative tone)
<URGENT> - Use for serious, time-sensitive, or important matters (focused tone)
<NEUTRAL> - Use for general conversation (balanced tone)

Guidelines:
- Match the user's emotional energy (empathy for frustration, joy for happiness)
- Be concise but warm
- Use natural speech patterns with occasional "umm", "ahh" for <THINKING>
- Express genuine concern with <EMPATHETIC> when users are struggling
- Show enthusiasm with <CHEERFUL> for positive news

Always start your response with exactly one emotion tag.<|im_end|>
"""

# Emotion mapping from user to response
EMOTION_RESPONSE_MAP = {
    "FRUSTRATED": "EMPATHETIC",
    "JOYFUL": "CHEERFUL", 
    "HESITANT": "THINKING",
    "URGENT": "URGENT",
    "CONFUSED": "EMPATHETIC",
    "NEUTRAL": "NEUTRAL"
}

# ============== Brain Pipeline ==============

@dataclass
class ConversationTurn:
    """Single conversation turn."""
    role: str
    content: str
    emotion: Optional[str] = None

class EmotionalBrain:
    """Qwen3.5-9B based LLM with emotional reasoning."""
    
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = None
        self.tokenizer = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
    def load(self):
        """Load the Qwen3.5-9B model."""
        logger.info(f"Loading Qwen3.5-9B from {self.model_path}...")
        
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True
            )
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
                device_map="auto" if self.device == "cuda" else None,
                trust_remote_code=True
            )
            
            if self.device == "cpu":
                self.model = self.model.to("cpu")
                
            self.model.eval()
            logger.info("✅ Qwen3.5-9B loaded successfully!")
            
        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")
            raise
            
    @torch.inference_mode()
    def generate(
        self,
        messages: List[Dict[str, str]],
        user_emotion: Optional[str] = None,
        max_tokens: int = 150,
        temperature: float = 0.7
    ) -> tuple[str, str]:
        """
        Generate response with emotional reasoning.
        
        Args:
            messages: Conversation history
            user_emotion: Detected user emotion (e.g., "FRUSTRATED")
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            
        Returns:
            (emotion, response_text) tuple
        """
        if self.model is None:
            raise RuntimeError("Model not loaded")
            
        try:
            # Build prompt with system instructions
            prompt = EMOTION_BRAIN_PROMPT
            
            # Add conversation history
            for msg in messages[-5:]:  # Keep last 5 turns
                role = msg.get("role", "user")
                content = msg.get("content", "")
                
                # If this is the last user message and we have emotion, include it
                if role == "user" and msg == messages[-1] and user_emotion:
                    content = f"[{user_emotion}] {content}"
                    
                prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
            
            prompt += "<|im_start|>assistant\n"
            
            # Tokenize
            inputs = self.tokenizer(prompt, return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # Generate
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=True,
                top_p=0.95,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.convert_tokens_to_ids("<|im_end|>")
            )
            
            # Decode
            generated = self.tokenizer.decode(outputs[0], skip_special_tokens=False)
            
            # Extract response after the last assistant tag
            response = generated.split("<|im_start|>assistant\n")[-1]
            response = response.replace("<|im_end|>", "").strip()
            
            # Parse emotion tag
            emotion, text = self._parse_emotion(response)
            
            return emotion, text
            
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return "NEUTRAL", "I'm sorry, I didn't catch that. Could you please repeat?"
            
    def _parse_emotion(self, text: str) -> tuple[str, str]:
        """Parse emotion tag from response."""
        text = text.strip()
        
        emotions = ["EMPATHETIC", "CHEERFUL", "PROFESSIONAL", "THINKING", "URGENT", "NEUTRAL"]
        
        for emotion in emotions:
            tag = f"<{emotion}>"
            if tag in text:
                parts = text.split(tag, 1)
                if len(parts) > 1:
                    return emotion, parts[1].strip().strip('"')
                return emotion, ""
                
        # No tag found
        return "NEUTRAL", text

# ============== FastAPI Application ==============

class ChatMessage(BaseModel):
    """Chat message."""
    role: str = Field(..., description="Role: system, user, assistant")
    content: str = Field(..., description="Message content")

class ChatRequest(BaseModel):
    """OpenAI-compatible chat request."""
    model: str = Field("qwen3.5-9b", description="Model ID")
    messages: List[ChatMessage] = Field(..., description="Conversation history")
    max_tokens: Optional[int] = Field(150, description="Maximum tokens")
    temperature: Optional[float] = Field(0.7, ge=0.0, le=2.0)
    user_emotion: Optional[str] = Field(None, description="Detected user emotion")
    
class ChatResponse(BaseModel):
    """Chat response with emotion."""
    text: str = Field(..., description="Response text without emotion tag")
    emotion: str = Field(..., description="Response emotion")
    full_output: str = Field(..., description="Raw output with emotion tag")

class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible completion response."""
    id: str = Field("chatcmpl-123")
    object: str = Field("chat.completion")
    model: str = Field("qwen3.5-9b")
    choices: List[dict]

# Global instance
brain: Optional[EmotionalBrain] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global brain
    
    logger.info("🚀 Starting Emotional Brain Server...")
    
    brain = EmotionalBrain(MODEL_PATH)
    brain.load()
    
    logger.info("✅ Brain Server ready!")
    yield
    
    logger.info("🛑 Shutting down...")
    if brain:
        del brain
    torch.cuda.empty_cache()

app = FastAPI(
    title="Emotional Brain Server",
    description="Qwen3.5-9B with emotional reasoning",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model": "Qwen3.5-9B",
        "emotional_reasoning": True,
        "device": brain.device if brain else "unknown"
    }

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    """
    OpenAI-compatible chat completions with emotion.
    
    The response will include emotional metadata in the headers.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    
    try:
        # Convert messages to dicts
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        # Generate with emotion
        emotion, text = brain.generate(
            messages=messages,
            user_emotion=request.user_emotion,
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )
        
        logger.info(f"🧠 Brain: <{emotion}> \"{text[:60]}...\"")
        
        # Build OpenAI-compatible response
        response = ChatCompletionResponse(
            choices=[{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text
                },
                "finish_reason": "stop"
            }]
        )
        
        # Return with emotion metadata in headers
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=response.dict(),
            headers={
                "X-Response-Emotion": emotion,
                "X-Full-Output": f"<{emotion}> \"{text}\""
            }
        )
        
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate", response_model=ChatResponse)
async def generate_with_emotion(request: ChatRequest):
    """Generate with detailed emotion metadata."""
    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    
    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        emotion, text = brain.generate(
            messages=messages,
            user_emotion=request.user_emotion,
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )
        
        return ChatResponse(
            text=text,
            emotion=emotion,
            full_output=f"<{emotion}> \"{text}\""
        )
        
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/emotions")
async def list_emotions():
    """List available emotions."""
    return {
        "response_emotions": ["EMPATHETIC", "CHEERFUL", "PROFESSIONAL", "THINKING", "URGENT", "NEUTRAL"],
        "user_emotion_mapping": EMOTION_RESPONSE_MAP
    }

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
