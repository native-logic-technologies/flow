/// Service clients for ASR, LLM, and TTS
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

/// Call Parakeet ASR gRPC endpoint
pub async fn parakeet_transcribe(url: &str, audio_bytes: Vec<u8>) -> Result<String> {
    // This is a placeholder - in production, use tonic gRPC client
    // For now, use HTTP endpoint if available
    
    let client = reqwest::Client::new();
    let response = client
        .post(format!("{}/transcribe", url))
        .body(audio_bytes)
        .send()
        .await
        .context("Failed to connect to ASR service")?;
    
    let result: serde_json::Value = response.json().await?;
    Ok(result
        .get("text")
        .and_then(|t| t.as_str())
        .unwrap_or("")
        .to_string())
}

/// LLM Service for Nemotron
pub struct LlmService {
    client: reqwest::Client,
    base_url: String,
}

impl LlmService {
    pub fn new(base_url: &str) -> Self {
        Self {
            client: reqwest::Client::new(),
            base_url: base_url.to_string(),
        }
    }

    pub async fn generate(&self, prompt: &str) -> Result<String> {
        let body = serde_json::json!({
            "model": "/model",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 100,
            "temperature": 0.0
        });

        let response = self
            .client
            .post(format!("{}/v1/chat/completions", self.base_url))
            .json(&body)
            .send()
            .await?;

        let result: serde_json::Value = response.json().await?;
        Ok(result
            .get("choices")
            .and_then(|c| c.get(0))
            .and_then(|c| c.get("message"))
            .and_then(|m| m.get("content"))
            .and_then(|c| c.as_str())
            .unwrap_or("")
            .to_string())
    }
}

/// TTS Service for MOSS-TTS
pub struct TtsService {
    url: String,
}

impl TtsService {
    pub fn new(url: &str) -> Self {
        Self {
            url: url.to_string(),
        }
    }

    /// Generate audio from text (non-streaming fallback)
    pub async fn generate(&self, text: &str) -> Result<Vec<u8>> {
        let client = reqwest::Client::new();
        let body = serde_json::json!({
            "text": text,
            "voice_id": "phil-conversational"
        });

        let response = client
            .post(format!("{}/tts", self.url))
            .json(&body)
            .send()
            .await?;

        Ok(response.bytes().await?.to_vec())
    }
}

#[derive(Serialize, Deserialize)]
pub struct TtsRequest {
    pub text: String,
    pub voice_id: String,
    pub speed: f32,
}

#[derive(Serialize, Deserialize)]
pub struct TtsResponse {
    pub audio: Vec<u8>,
    pub sample_rate: u32,
}
