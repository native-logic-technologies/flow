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

/// Process LLM -> TTS pipeline with MICRO-CHUNKING for <500ms latency
/// 
/// This function streams LLM tokens to TTS incrementally instead of buffering
/// the full response. Total latency = max(LLM TTFT, TTS TTFT) ~ 300-450ms
#[instrument(skip(config, http_client, conversation, state, cancel_token, egress_tx))]
pub async fn process_llm_tts_micro(
    config: &AgentConfig,
    http_client: &Client,
    conversation: &Arc<RwLock<Vec<serde_json::Value>>>,
    state: &Arc<RwLock<CallState>>,
    cancel_token: &Arc<Mutex<CancellationToken>>,
    egress_tx: Option<&mpsc::Sender<Bytes>>,
) -> anyhow::Result<()> {
    use tokio_tungstenite::connect_async;
    use tokio_tungstenite::tungstenite::Message;
    
    *state.write().await = CallState::Thinking;
    
    // Layer 3: Prompt kill switch with BACKCHANNELING
    let messages = {
        let mut msgs = vec![
            json!({"role": "system", "content": "You are Phil having a natural phone conversation. Use occasional filler words like 'um', 'ahh', 'hmm' and backchanneling ('I see', 'right', 'got it') for natural speech. Keep responses SHORT (1-2 sentences). Speak conversationally without formatting."}),
            // Few-shot examples with natural fillers and backchanneling
            json!({"role": "user", "content": "Hey, are you there?"}),
            json!({"role": "assistant", "content": "Yeah, I'm here! What's up?"}),
            json!({"role": "user", "content": "What's the weather like?"}),
            json!({"role": "assistant", "content": "Hmm, not sure! Hope it's sunny though."}),
            json!({"role": "user", "content": "I'm feeling stressed about work"}),
            json!({"role": "assistant", "content": "Ahh, I hear you. Work can be tough sometimes, right?"}),
        ];
        // Add the actual conversation history
        msgs.extend(conversation.read().await.clone());
        msgs
    };
    
    // Call Nemotron LLM - 3-Layer Reasoning Kill Switch + SPEED OPTIMIZATION
    let llm_request = json!({
        "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
        "messages": messages,
        "stream": true,
        "max_tokens": 100,  // Shorter responses for faster generation
        "temperature": 0.7,  // Slightly higher for natural variation including fillers
        "top_p": 0.95,
        "presence_penalty": 0.2,
        "frequency_penalty": 0.2,
        // Speed optimizations
        "min_tokens": 5,
        "skip_special_tokens": false,
        // Layer 2: Mathematical kill switch - ban reasoning tokens
        "bad_words": [
            "<think>", "</think>", "<|reasoning|>", "<thought>", "</thought>",
            "The user said", "The user asks", "I need to respond",
            "We are starting", "I should say", "The question is"
        ]
    });
    
    info!("Calling Nemotron LLM (micro-chunking mode)...");
    
    // Start LLM request
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
    
    // STEP 1: Open TTS WebSocket IMMEDIATELY (before reading LLM)
    let tts_ws_url = config.tts_url.replace("http://", "ws://")
        .replace("https://", "wss://")
        .replace("/v1/audio/speech", "/ws/tts");
    
    info!("Connecting to TTS WebSocket at {} (micro-chunking)", tts_ws_url);
    let (mut tts_ws, _) = connect_async(&tts_ws_url).await?;
    
    // Send init to TTS
    let init_msg = json!({
        "type": "init",
        "voice": config.voice.as_deref().unwrap_or("default")
    });
    tts_ws.send(Message::Text(init_msg.to_string())).await?;
    
    // Wait for TTS ready
    let ready_msg = tts_ws.next().await.ok_or_else(|| anyhow::anyhow!("TTS WebSocket closed before ready"))??;
    if let Message::Text(text) = ready_msg {
        let status: serde_json::Value = serde_json::from_str(&text)?;
        if status.get("status").and_then(|s| s.as_str()) != Some("ready") {
            anyhow::bail!("TTS WebSocket did not become ready: {}", text);
        }
    }
    
    info!("TTS WebSocket ready - starting micro-chunking stream");
    
    // STEP 2: Stream LLM tokens to TTS as they arrive
    let mut llm_stream = response.bytes_stream();
    let mut token_buffer = String::new();
    let mut full_response = String::new();
    let mut first_token_time: Option<std::time::Instant> = None;
    let mut sse_buffer = String::new();
    
    while let Some(chunk_result) = llm_stream.next().await {
        if cancel_token.lock().await.is_cancelled() {
            info!("TTS cancelled (barge-in)");
            let _ = tts_ws.send(Message::Text(json!({"type": "end"}).to_string())).await;
            return Ok(());
        }
        
        let chunk = match chunk_result {
            Ok(c) => c,
            Err(e) => {
                error!("Error reading LLM stream: {}", e);
                break;
            }
        };
        
        // Convert bytes to string, handling potential UTF-8 issues
        let text = String::from_utf8_lossy(&chunk);
        sse_buffer.push_str(&text);
        
        // Process complete lines from SSE buffer
        while let Some(newline_pos) = sse_buffer.find('\n') {
            let line = sse_buffer[..newline_pos].to_string();
            sse_buffer = sse_buffer[newline_pos + 1..].to_string();
            
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            
            if let Some(data) = line.strip_prefix("data: ") {
                if data == "[DONE]" {
                    // Send any remaining tokens
                    if !token_buffer.is_empty() {
                        let sanitized = sanitize_for_tts(&strip_reasoning_tags(&token_buffer));
                        if !sanitized.is_empty() {
                            let msg = json!({"type": "text", "text": sanitized});
                            tts_ws.send(Message::Text(msg.to_string())).await?;
                        }
                    }
                    break;
                }
                
                if let Ok(json_data) = serde_json::from_str::<serde_json::Value>(data) {
                    if let Some(content) = json_data
                        .get("choices")
                        .and_then(|c| c.get(0))
                        .and_then(|c| c.get("delta"))
                        .and_then(|d| d.get("content"))
                        .and_then(|c| c.as_str())
                    {
                        // Record first token time
                        if first_token_time.is_none() {
                            first_token_time = Some(std::time::Instant::now());
                            info!("First LLM token received!");
                        }
                        
                        token_buffer.push_str(content);
                        full_response.push_str(content);
                        
                        // AGGRESSIVE: Send to TTS on small chunks for sub-500ms latency
                        let should_send = token_buffer.len() >= 5
                            || content.ends_with('.')
                            || content.ends_with('!')
                            || content.ends_with('?')
                            || content.ends_with(',')
                            || content.ends_with(' ');
                        
                        if should_send && !token_buffer.is_empty() {
                            let sanitized = sanitize_for_tts(&strip_reasoning_tags(&token_buffer));
                            if !sanitized.is_empty() {
                                let msg = json!({"type": "text", "text": sanitized});
                                tts_ws.send(Message::Text(msg.to_string())).await?;
                            }
                            token_buffer.clear();
                        }
                    }
                }
            }
        }
    }
    
    // STEP 3: Send END signal to TTS
    tts_ws.send(Message::Text(json!({"type": "end"}).to_string())).await?;
    
    // STEP 4: Receive audio chunks and forward immediately
    let mut total_bytes = 0;
    let mut chunk_count = 0;
    let mut first_audio_time: Option<std::time::Instant> = None;
    
    while let Some(msg_result) = tts_ws.next().await {
        match msg_result? {
            Message::Binary(data) => {
                if first_audio_time.is_none() {
                    first_audio_time = Some(std::time::Instant::now());
                    if let Some(ttft) = first_token_time {
                        info!("First audio received! Latency from first token: {:?}", first_audio_time.unwrap().duration_since(ttft));
                    }
                }
                
                total_bytes += data.len();
                chunk_count += 1;
                
                if let Some(tx) = &egress_tx {
                    if tx.send(Bytes::from(data)).await.is_err() {
                        info!("Egress channel closed");
                        break;
                    }
                }
            }
            Message::Text(text) => {
                let status: serde_json::Value = serde_json::from_str(&text)?;
                if status.get("status").and_then(|s| s.as_str()) == Some("complete") {
                    info!("TTS streaming complete: {} chunks, {} bytes", chunk_count, total_bytes);
                    break;
                } else if status.get("error").is_some() {
                    anyhow::bail!("TTS error: {}", text);
                }
            }
            Message::Close(_) => break,
            _ => {}
        }
    }
    
    // Add assistant response to conversation
    let cleaned_response = strip_reasoning_tags(&full_response);
    if !cleaned_response.is_empty() {
        conversation.write().await.push(json!({
            "role": "assistant",
            "content": cleaned_response
        }));
    }
    
    *state.write().await = CallState::Listening;
    Ok(())
}

/// Optimized LLM -> TTS with sentence-level streaming for low latency
/// 
/// This buffers sentences and sends them to TTS immediately for <1s latency
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
    
    // Updated system prompt with backchanneling and natural fillers
    let messages = {
        let mut msgs = vec![
            json!({"role": "system", "content": "You are Phil having a natural phone conversation. Use occasional filler words like 'um', 'ahh', 'hmm' and backchanneling ('I see', 'right', 'got it') for natural speech. Keep responses SHORT (1-2 sentences). Respond immediately without thinking."}),
            // Few-shot examples
            json!({"role": "user", "content": "Hey, are you there?"}),
            json!({"role": "assistant", "content": "Yeah, I'm here! What's up?"}),
            json!({"role": "user", "content": "What's the weather like?"}),
            json!({"role": "assistant", "content": "Hmm, not sure! Hope it's sunny though."}),
        ];
        msgs.extend(conversation.read().await.clone());
        msgs
    };
    
    // Optimized LLM request for speed
    let llm_request = json!({
        "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
        "messages": messages,
        "stream": true,
        "max_tokens": 80,  // Shorter for speed
        "temperature": 0.8, // Natural variation
        "top_p": 0.95,
        "presence_penalty": 0.1,
        "frequency_penalty": 0.1,
        "bad_words": ["<think>", "</think>", "The user said", "I need to respond"]
    });
    
    info!("Calling Nemotron LLM (optimized)...");
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
    
    // Stream response and send sentences to TTS immediately
    let mut sentence_buffer = String::new();
    let mut full_response = String::new();
    let mut stream = response.bytes_stream();
    
    while let Some(chunk) = stream.next().await {
        if cancel_token.lock().await.is_cancelled() {
            info!("TTS cancelled (barge-in)");
            return Ok(());
        }
        
        let chunk = chunk?;
        let text = String::from_utf8_lossy(&chunk);
        
        // Parse SSE
        for line in text.lines() {
            if let Some(data) = line.strip_prefix("data: ") {
                if data == "[DONE]" {
                    // Flush remaining via WebSocket
                    let cleaned = strip_reasoning_tags(&sentence_buffer);
                    let tts_ready = sanitize_for_tts(&cleaned);
                    if !tts_ready.is_empty() && tts_ready.len() >= 3 {
                        info!("TTS WebSocket final: {}", tts_ready);
                        if let Err(e) = generate_tts_websocket(&tts_ready, config, egress_tx).await {
                            error!("WebSocket TTS final failed: {}", e);
                        }
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
                        sentence_buffer.push_str(content);
                        full_response.push_str(content);
                        
                        // Send on sentence end OR every 15 chars for faster response
                        if content.ends_with('.') || content.ends_with('!') || content.ends_with('?') 
                           || (sentence_buffer.len() >= 15 && content.ends_with(' ')) {
                            let cleaned = strip_reasoning_tags(&sentence_buffer);
                            let tts_ready = sanitize_for_tts(&cleaned);
                            
                            if !tts_ready.is_empty() && tts_ready.len() >= 3 {
                                info!("TTS WebSocket stream: {}", tts_ready);
                                
                                // Spawn WebSocket TTS in parallel for lower latency
                                let tts_text = tts_ready.to_string();
                                let tts_config = config.clone();
                                let tts_egress = egress_tx.map(|tx| tx.clone());
                                
                                tokio::spawn(async move {
                                    // Use WebSocket TTS for sub-500ms latency
                                    if let Err(e) = generate_tts_websocket(&tts_text, &tts_config, tts_egress.as_ref()).await {
                                        error!("WebSocket TTS failed: {}", e);
                                    }
                                });
                            }
                            
                            sentence_buffer.clear();
                        }
                    }
                }
            }
        }
    }
    
    // Add to conversation
    let cleaned = strip_reasoning_tags(&full_response);
    if !cleaned.is_empty() {
        conversation.write().await.push(json!({
            "role": "assistant",
            "content": cleaned
        }));
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

/// Generate TTS audio from text using WebSocket streaming for low latency
/// 
/// This function connects to MOSS-TTS via WebSocket and streams text tokens
/// as they arrive, enabling <500ms latency by overlapping LLM generation with TTS synthesis.
#[instrument(skip(text, config, egress_tx))]
pub async fn generate_tts_websocket(
    text: &str,
    config: &AgentConfig,
    egress_tx: Option<&mpsc::Sender<Bytes>>,
) -> anyhow::Result<()> {
    use tokio_tungstenite::connect_async;
    use tokio_tungstenite::tungstenite::Message;
    
    let tts_ws_url = config.tts_url.replace("http://", "ws://").replace("https://", "wss://").replace("/v1/audio/speech", "/ws/tts");
    
    info!("Connecting to TTS WebSocket at {}", tts_ws_url);
    
    let (mut ws_stream, _) = connect_async(&tts_ws_url).await?;
    
    // Send init message
    let init_msg = json!({
        "type": "init",
        "voice": config.voice.as_deref().unwrap_or("default")
    });
    ws_stream.send(Message::Text(init_msg.to_string())).await?;
    
    // Wait for ready response
    let ready_msg = ws_stream.next().await.ok_or_else(|| anyhow::anyhow!("TTS WebSocket closed before ready"))??;
    if let Message::Text(text) = ready_msg {
        let status: serde_json::Value = serde_json::from_str(&text)?;
        if status.get("status").and_then(|s| s.as_str()) != Some("ready") {
            anyhow::bail!("TTS WebSocket did not become ready: {}", text);
        }
    }
    
    info!("TTS WebSocket ready, streaming text: '{}'", text);
    
    // Stream text to TTS (can be sent character by character for true streaming)
    // For efficiency, we send in small chunks
    let chars: Vec<char> = text.chars().collect();
    let chunk_size = 3; // Send ~3 chars at a time
    
    for chunk in chars.chunks(chunk_size) {
        let text_chunk: String = chunk.iter().collect();
        let msg = json!({
            "type": "text",
            "text": text_chunk
        });
        ws_stream.send(Message::Text(msg.to_string())).await?;
    }
    
    // Send end message
    let end_msg = json!({"type": "end"});
    ws_stream.send(Message::Text(end_msg.to_string())).await?;
    
    // Receive audio chunks
    let mut total_bytes = 0;
    let mut chunk_count = 0;
    let mut complete = false;
    
    while let Some(msg) = ws_stream.next().await {
        match msg? {
            Message::Binary(data) => {
                total_bytes += data.len();
                chunk_count += 1;
                
                if let Some(tx) = &egress_tx {
                    if tx.send(Bytes::from(data)).await.is_err() {
                        info!("Egress channel closed during TTS");
                        break;
                    }
                }
            }
            Message::Text(text) => {
                let status: serde_json::Value = serde_json::from_str(&text)?;
                if status.get("status").and_then(|s| s.as_str()) == Some("complete") {
                    complete = true;
                    break;
                } else if status.get("error").is_some() {
                    anyhow::bail!("TTS error: {}", text);
                }
            }
            Message::Close(_) => break,
            _ => {}
        }
    }
    
    info!("TTS WebSocket complete: {} chunks, {} bytes, complete={}", chunk_count, total_bytes, complete);
    
    Ok(())
}

/// Generate TTS audio from text using HTTP (fallback for non-streaming)
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
        
        if let Some(tx) = egress_tx {
            if tx.send(chunk).await.is_err() {
                info!("Egress channel closed, sent {} chunks ({} bytes)", chunk_count, total_bytes);
                break;
            }
        }
    }
    
    info!("TTS streaming complete: {} chunks, {} bytes total", chunk_count, total_bytes);
    
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
