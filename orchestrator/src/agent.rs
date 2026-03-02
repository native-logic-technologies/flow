//! LiveKit Telephony Agent
//! 
//! Implements the zero-latency state machine for speech-to-speech conversations.
//! Handles ingress (listening) and egress (speaking) with barge-in support.
//!
//! # Complete Audio Pipeline
//!
//! 1. **LiveKit (Rust)**: Receives raw 8kHz RTP packets from SIP/WebRTC
//! 2. **DeepFilterNet v0.5.6 (Rust)**: Noise suppression (< 2ms, pure Rust tract backend)
//! 3. **Silero VAD (Rust)**: Voice activity detection (< 1ms, ONNX Runtime)
//! 4. **Voxtral ASR (vLLM)**: Transcription via WebSocket (~40ms)
//! 5. **Nemotron LLM (vLLM)**: Response generation with reasoning disabled (~80ms TTFT)
//! 6. **MOSS-TTS (FastAPI)**: Voice cloning + synthesis (~100ms)
//! 7. **LiveKit (Rust)**: Audio playback to phone line
//!
//! Total E2E Latency: ~250ms

use crate::vad::{SileroVad, VAD_CHUNK_SAMPLES, VAD_SAMPLE_RATE, SILENCE_TIMEOUT_MS};
use bytes::Bytes;
use futures_util::{SinkExt, StreamExt};
use reqwest::Client;
use serde_json::json;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex, RwLock};
use tokio::time::{timeout, Duration, Instant};
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, instrument, warn};

/// Audio processing constants
const ASR_SAMPLE_RATE: usize = 8000;
const TTS_SAMPLE_RATE: usize = 24000;
const WEBRTC_BUFFER_MS: usize = 20;

/// Call states for the state machine
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum CallState {
    /// Waiting for speech
    Listening,
    /// Speech detected, streaming to ASR
    Processing,
    /// Got transcription, waiting for LLM
    Thinking,
    /// Streaming LLM tokens to TTS
    Speaking,
    /// Call ended
    Ended,
}

/// Configuration for the telephony agent
#[derive(Debug, Clone)]
pub struct AgentConfig {
    /// Voxtral ASR WebSocket URL
    pub asr_ws_url: String,
    /// Nemotron LLM HTTP endpoint
    pub llm_url: String,
    /// MOSS-TTS HTTP endpoint
    pub tts_url: String,
    /// Voice for TTS (or reference audio for zero-shot)
    pub voice: Option<String>,
    /// LLM system prompt
    pub system_prompt: String,
}

impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            asr_ws_url: "http://127.0.0.1:8003/v1/audio/transcriptions".to_string(), // ASR Bridge
            llm_url: "http://127.0.0.1:8000/v1/chat/completions".to_string(),
            tts_url: "http://127.0.0.1:8002/v1/audio/speech".to_string(),
            voice: None,
            system_prompt: r#"You are a helpful voice assistant on a live phone call. 

CRITICAL INSTRUCTIONS:
1. Respond instantly - NO internal thinking, reasoning, or monologue
2. Use natural conversational fillers: "um", "ahh", "let me see", "hmm"
3. Use pauses: "..." or ".." for natural speech rhythm
4. Use backchanneling: "Mmm hmm", "I see", "Right", "Got it"
5. Keep responses SHORT (1-2 sentences typical)
6. Do NOT use <think>, <thought>, or any reasoning tags
7. Output ONLY the spoken words - nothing else

Example natural responses:
- "Um, let me check that for you... okay, I found it."
- "Mmm hmm, I see... so what you're saying is..."
- "Ahh, okay... well, the best option would be..."

Remember: This is a voice conversation. Be warm, conversational, and human."#.to_string(),
        }
    }
}

/// Per-call state and resources
pub struct TelephonyAgent {
    pub config: AgentConfig,
    /// HTTP client for LLM/TTS
    pub http_client: Client,
    /// VAD instance (per-call for state isolation)
    vad: Arc<Mutex<SileroVad>>,
    /// Current call state
    pub state: Arc<RwLock<CallState>>,
    /// Cancellation token for barge-in
    pub tts_cancel: Arc<Mutex<CancellationToken>>,
    /// Conversation history for LLM context
    pub conversation: Arc<RwLock<Vec<serde_json::Value>>>,
    /// Call start time
    start_time: Instant,
}

impl TelephonyAgent {
    /// Create a new telephony agent instance
    pub fn new(config: AgentConfig, vad_model_path: &str) -> anyhow::Result<Self> {
        let http_client = Client::builder()
            .timeout(Duration::from_secs(30))
            .pool_max_idle_per_host(10)
            .build()?;
        
        let vad = SileroVad::new(vad_model_path)?;
        
        Ok(Self {
            config,
            http_client,
            vad: Arc::new(Mutex::new(vad)),
            state: Arc::new(RwLock::new(CallState::Listening)),
            tts_cancel: Arc::new(Mutex::new(CancellationToken::new())),
            conversation: Arc::new(RwLock::new(vec![
                // Pre-load the greeting so LLM knows it already introduced itself
                json!({
                    "role": "assistant",
                    "content": "Hey there! I'm Phil. How can I help you today?"
                })
            ])),
            start_time: Instant::now(),
        })
    }
    
    /// Main entry point: handle a new call
    /// 
    /// # Arguments
    /// * `ingress_rx` - Receiver for incoming audio from LiveKit
    /// * `egress_tx` - Sender for outgoing audio to LiveKit
    #[instrument(skip(self, ingress_rx, egress_tx))]
    pub async fn handle_call(
        &self,
        mut ingress_rx: mpsc::Receiver<Bytes>,
        egress_tx: mpsc::Sender<Bytes>,
    ) -> anyhow::Result<()> {
        info!("Starting call handling");
        
        // Spawn ingress task (listening)
        let ingress_handle = self.spawn_ingress_task(ingress_rx);
        
        // Spawn egress task (speaking)
        let egress_handle = self.spawn_egress_task(egress_tx);
        
        // Wait for completion or error
        tokio::select! {
            result = ingress_handle => {
                info!("Ingress task completed: {:?}", result);
            }
            result = egress_handle => {
                info!("Egress task completed: {:?}", result);
            }
        }
        
        // Mark call ended
        *self.state.write().await = CallState::Ended;
        
        Ok(())
    }
    
    /// Ingress loop: process incoming audio, VAD, trigger transcription on silence
    fn spawn_ingress_task(&self, mut rx: mpsc::Receiver<Bytes>) -> tokio::task::JoinHandle<()> {
        let vad = Arc::clone(&self.vad);
        let state = Arc::clone(&self.state);
        let config = self.config.clone();
        let http_client = self.http_client.clone();
        let conversation = Arc::clone(&self.conversation);
        let tts_cancel = Arc::clone(&self.tts_cancel);
        
        tokio::spawn(async move {
            let mut speech_buffer: Vec<f32> = Vec::new();
            let mut last_speech = Instant::now();
            let mut is_collecting = false;
            
            info!("Ingress task started - waiting for speech...");
            
            while let Some(audio_bytes) = rx.recv().await {
                // Convert bytes to f32 PCM
                let samples = bytes_to_f32(&audio_bytes);
                
                // Process in VAD-sized chunks (256 samples @ 8kHz = 32ms)
                for chunk in samples.chunks(VAD_CHUNK_SAMPLES) {
                    if chunk.len() < VAD_CHUNK_SAMPLES {
                        continue;
                    }
                    let chunk_arr: [f32; VAD_CHUNK_SAMPLES] = chunk.try_into().unwrap();
                    
                    // Run VAD
                    let is_speech = {
                        let mut vad = vad.lock().await;
                        vad.is_speech(&chunk_arr)
                    };
                    
                    if is_speech {
                        // Speech detected
                        if !is_collecting {
                            info!("Speech detected - starting collection");
                            is_collecting = true;
                            speech_buffer.clear();
                        }
                        last_speech = Instant::now();
                        speech_buffer.extend_from_slice(chunk);
                        
                        // Check for barge-in
                        let current_state = *state.read().await;
                        if current_state == CallState::Speaking {
                            info!("Barge-in detected! Cancelling TTS...");
                            tts_cancel.lock().await.cancel();
                            *state.write().await = CallState::Processing;
                        }
                    } else if is_collecting {
                        // Silence while collecting
                        speech_buffer.extend_from_slice(chunk);
                        
                        // Check if silence timeout
                        if last_speech.elapsed() > Duration::from_millis(SILENCE_TIMEOUT_MS) {
                            info!("Silence timeout - processing {} samples", speech_buffer.len());
                            
                            // Send to ASR Bridge
                            let asr_url = config.asr_ws_url.clone();
                            let http_client = http_client.clone();
                            
                            // Convert f32 samples back to i16 PCM
                            let pcm_bytes: Vec<u8> = speech_buffer
                                .iter()
                                .map(|&s| (s * 32767.0) as i16)
                                .flat_map(|s| s.to_le_bytes().to_vec())
                                .collect();
                            
                            let audio_b64 = base64::Engine::encode(
                                &base64::engine::general_purpose::STANDARD,
                                &pcm_bytes
                            );
                            
                            let asr_request = json!({
                                "audio": audio_b64,
                                "sample_rate": 8000,
                                "language": "en",
                                "format": "pcm"
                            });
                            
                            match http_client.post(&asr_url)
                                .json(&asr_request)
                                .timeout(Duration::from_secs(10))
                                .send().await 
                            {
                                Ok(resp) => {
                                    if resp.status().is_success() {
                                        if let Ok(asr_result) = resp.json::<serde_json::Value>().await {
                                            if let Some(text) = asr_result.get("text").and_then(|t| t.as_str()) {
                                                info!("ASR transcription: {}", text);
                                                
                                                if !text.is_empty() && text != "[Transcription failed]" {
                                                    // Add to conversation
                                                    conversation.write().await.push(json!({
                                                        "role": "user",
                                                        "content": text
                                                    }));
                                                    
                                                    *state.write().await = CallState::Thinking;
                                                    
                                                    // Trigger LLM + TTS pipeline
                                                    let tts_cancel_clone = Arc::clone(&tts_cancel);
                                                    let conversation_clone = Arc::clone(&conversation);
                                                    let config_clone = config.clone();
                                                    let http_client_clone = http_client.clone();
                                                    let state_clone = Arc::clone(&state);
                                                    
                                                    tokio::spawn(async move {
                                                        if let Err(e) = process_llm_tts(
                                                            &config_clone,
                                                            &http_client_clone,
                                                            &conversation_clone,
                                                            &state_clone,
                                                            &tts_cancel_clone,
                                                            None, // Voice mode uses normal egress
                                                        ).await {
                                                            error!("LLM/TTS processing failed: {}", e);
                                                        }
                                                    });
                                                }
                                            }
                                        }
                                    } else {
                                        error!("ASR request failed: {}", resp.status());
                                    }
                                }
                                Err(e) => {
                                    error!("ASR request error: {}", e);
                                }
                            }
                            
                            // Reset collection
                            is_collecting = false;
                            speech_buffer.clear();
                            *state.write().await = CallState::Listening;
                        }
                    }
                }
            }
            
            info!("Ingress loop ended");
        })
    }
    
    /// Egress task: wait for call to end (actual egress handled by WebSocket task in main.rs)
    fn spawn_egress_task(&self, _tx: mpsc::Sender<Bytes>) -> tokio::task::JoinHandle<()> {
        // The actual egress (sending audio to WebSocket) is handled by the egress_handle
        // in main.rs. This task just waits indefinitely until the call ends.
        let state = Arc::clone(&self.state);
        tokio::spawn(async move {
            info!("Egress task started (waiting for call end)");
            // Wait until call state is Ended
            loop {
                let current_state = *state.read().await;
                if current_state == CallState::Ended {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            info!("Egress task ending (call ended)");
        })
    }
}

/// Process LLM -> TTS pipeline
#[instrument(skip(config, http_client, conversation, state, cancel_token, egress_tx))]
pub async fn process_llm_tts(
    config: &AgentConfig,
    http_client: &Client,
    conversation: &Arc<RwLock<Vec<serde_json::Value>>>,
    state: &Arc<RwLock<CallState>>,
    cancel_token: &Arc<Mutex<CancellationToken>>,
    egress_tx: Option<&mpsc::Sender<Bytes>>,
) -> anyhow::Result<()> {
    *state.write().await = CallState::Thinking;
    
    // Build messages with few-shot pattern forcing
    // This locks the model into "dialogue mode" instead of "thinking mode"
    let messages = {
        let mut msgs = vec![
            json!({
                "role": "system",
                "content": "You are Phil, having a casual phone conversation. Keep responses under 2 sentences. Be direct, friendly, and conversational."
            }),
            // Few-shot examples to force the pattern
            json!({"role": "user", "content": "Hey, is anyone there?"}),
            json!({"role": "assistant", "content": "Hey! Yeah, I'm here. What's up?"}),
            json!({"role": "user", "content": "What's the weather like?"}),
            json!({"role": "assistant", "content": "Um... not sure, but I hope it's sunny! Why do you ask?"}),
        ];
        // Add the actual conversation history
        msgs.extend(conversation.read().await.clone());
        msgs
    };
    
    // Call Nemotron LLM with pattern forcing
    let llm_request = json!({
        "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
        "messages": messages,
        "stream": true,
        "max_tokens": 80,
        "temperature": 0.4,
        "presence_penalty": 0.6,
        "frequency_penalty": 0.3
    });
    
    info!("Calling Nemotron LLM...");
    let response = http_client
        .post(&config.llm_url)
        .json(&llm_request)
        .send()
        .await?;
    
    if !response.status().is_success() {
        let error_text = response.text().await?;
        anyhow::bail!("LLM request failed: {}", error_text);
    }
    
    *state.write().await = CallState::Speaking;
    
    // Stream LLM tokens and collect full response for TTS
    let mut response_buffer = String::new();
    let mut stream = response.bytes_stream();
    
    while let Some(chunk) = stream.next().await {
        if cancel_token.lock().await.is_cancelled() {
            info!("TTS cancelled (barge-in)");
            return Ok(());
        }
        
        let chunk = chunk?;
        let text = String::from_utf8_lossy(&chunk);
        
        // Parse SSE format (data: {...})
        for line in text.lines() {
            if let Some(data) = line.strip_prefix("data: ") {
                if data == "[DONE]" {
                    // Generate TTS for the complete response
                    let cleaned = strip_reasoning_tags(&response_buffer);
                    // CRITICAL: Sanitize for TTS (remove emojis, markdown, etc.)
                    let tts_ready = sanitize_for_tts(&cleaned);
                    if !tts_ready.is_empty() && tts_ready.len() >= 10 {
                        info!("TTS text ({} chars): {}", tts_ready.len(), tts_ready);
                        generate_tts(&tts_ready, config, http_client, egress_tx).await?;
                    }
                    break;
                }
                
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(data) {
                    if let Some(content) = json
                        .get("choices")
                        .and_then(|c| c.get(0))
                        .and_then(|c| c.get("delta"))
                        .and_then(|d| d.get("content"))
                        .and_then(|c| c.as_str())
                    {
                        response_buffer.push_str(content);
                    }
                }
            }
        }
    }
    
    *state.write().await = CallState::Listening;
    Ok(())
}

/// Strip reasoning tags and thinking text from LLM output
fn strip_reasoning_tags(text: &str) -> String {
    // Remove common reasoning tags
    let mut result = text.to_string();
    let tags = ["<think>", "</think>", "<thought>", "</thought>", "<|reasoning|>"];
    
    for tag in &tags {
        result = result.replace(tag, "");
    }
    
    // Detect and strip reasoning/thinking patterns
    let trimmed = result.trim();
    
    // If it looks like reasoning/instructions, return empty
    let reasoning_patterns = [
        "we are starting",
        "the user said",
        "as per instructions",
        "i must respond",
        "i should",
        "i can say",
        "let me",
        "i need to",
        "according to",
        "following the",
        "the instruction says",
    ];
    
    let lower = trimmed.to_lowercase();
    for pattern in &reasoning_patterns {
        if lower.contains(pattern) {
            return String::new(); // Return empty - this is reasoning
        }
    }
    
    // Strip if text starts with < or [ (likely reasoning start)
    if trimmed.starts_with('<') || trimmed.starts_with('[') {
        if let Some(pos) = trimmed.find(|c: char| c.is_alphanumeric()) {
            result = trimmed[pos..].to_string();
        }
    }
    
    result.trim().to_string()
}

/// Sanitize text for TTS - remove emojis, markdown, and special characters
/// that MOSS-TTS cannot pronounce
fn sanitize_for_tts(input: &str) -> String {
    // Filter to ASCII alphanumeric, basic punctuation, and whitespace
    // Remove emojis, markdown (*, _), brackets, and other special chars
    input
        .chars()
        .filter(|c| {
            // Keep ASCII alphanumeric
            c.is_ascii_alphanumeric() ||
            // Keep basic punctuation (but not * or brackets)
            (c.is_ascii_punctuation() && *c != '*' && *c != '_' && *c != '[' && *c != ']' && *c != '<' && *c != '>') ||
            // Keep whitespace
            c.is_whitespace()
        })
        .collect::<String>()
        .trim()
        .to_string()
}

/// Generate TTS audio from text
#[instrument(skip(text, config, http_client, egress_tx))]
pub async fn generate_tts(
    text: &str,
    config: &AgentConfig,
    http_client: &Client,
    egress_tx: Option<&mpsc::Sender<Bytes>>,
) -> anyhow::Result<()> {
    info!("Generating TTS for: {}", text);
    
    let mut tts_request = json!({
        "model": "OpenMOSS-Team/MOSS-TTS-Realtime",
        "input": text,
        "voice": config.voice.as_deref().unwrap_or("default"),
        "response_format": "pcm"
    });
    
    // Add zero-shot voice cloning if reference audio provided
    // CRITICAL: reference_text must be provided and should match the content of the reference audio
    if let Some(ref_audio) = &config.voice {
        if ref_audio.starts_with("data:audio") || ref_audio.len() > 100 {
            tts_request["extra_body"] = json!({
                "reference_audio": ref_audio,
                "reference_text": "I really didn't expect the weather to change so quickly."
            });
        }
    }
    
    let response = http_client
        .post(&config.tts_url)
        .json(&tts_request)
        .send()
        .await?;
    
    if !response.status().is_success() {
        let error_text = response.text().await?;
        anyhow::bail!("TTS request failed: {}", error_text);
    }
    
    // Stream audio chunks to egress
    let mut stream = response.bytes_stream();
    let mut total_bytes = 0;
    let mut chunk_count = 0;
    
    info!("Starting TTS audio stream...");
    
    while let Some(chunk_result) = stream.next().await {
        let chunk = chunk_result?;
        let chunk_len = chunk.len();
        total_bytes += chunk_len;
        chunk_count += 1;
        
        info!("TTS chunk {}: {} bytes", chunk_count, chunk_len);
        
        // Send to egress channel if provided
        if let Some(tx) = egress_tx {
            if tx.send(chunk).await.is_err() {
                info!("Egress channel closed, sent {} chunks ({} bytes)", chunk_count, total_bytes);
                break;
            }
        }
    }
    
    info!("TTS streaming complete: {} chunks, {} bytes total for text: '{}'", chunk_count, total_bytes, text);
    
    Ok(())
}

/// Convert PCM bytes to f32 samples
fn bytes_to_f32(bytes: &Bytes) -> Vec<f32> {
    bytes
        .chunks_exact(2)
        .map(|chunk| {
            let sample = i16::from_le_bytes([chunk[0], chunk[1]]);
            sample as f32 / 32768.0
        })
        .collect()
}
