//! LiveKit Telephony Agent
//! 
//! Implements the zero-latency state machine for speech-to-speech conversations.
//! Handles ingress (listening) and egress (speaking) with barge-in support.

use crate::vad::{SileroVad, VAD_CHUNK_SAMPLES, VAD_SAMPLE_RATE, SILENCE_TIMEOUT_MS};
use bytes::Bytes;
use futures_util::{SinkExt, StreamExt};
use reqwest::Client;
use serde_json::json;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex, RwLock};
use tokio::time::{timeout, Duration, Instant};
use tokio_cancellation_token::CancellationToken;
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
            asr_ws_url: "ws://127.0.0.1:8001/v1/realtime".to_string(),
            llm_url: "http://127.0.0.1:8000/v1/chat/completions".to_string(),
            tts_url: "http://127.0.0.1:8002/v1/audio/speech".to_string(),
            voice: None,
            system_prompt: "You are a helpful voice assistant.".to_string(),
        }
    }
}

/// Per-call state and resources
pub struct TelephonyAgent {
    config: AgentConfig,
    /// HTTP client for LLM/TTS
    http_client: Client,
    /// VAD instance (per-call for state isolation)
    vad: Arc<Mutex<SileroVad>>,
    /// Current call state
    state: Arc<RwLock<CallState>>,
    /// Cancellation token for barge-in
    tts_cancel: Arc<Mutex<CancellationToken>>,
    /// Conversation history for LLM context
    conversation: Arc<RwLock<Vec<serde_json::Value>>>,
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
            conversation: Arc::new(RwLock::new(Vec::new())),
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
        let ingress_handle = self.spawn_ingress_task(ingress_rx.resubscribe());
        
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
    
    /// Ingress loop: process incoming audio, VAD, ASR
    fn spawn_ingress_task(&self, mut rx: mpsc::Receiver<Bytes>) -> tokio::task::JoinHandle<()> {
        let vad = Arc::clone(&self.vad);
        let state = Arc::clone(&self.state);
        let config = self.config.clone();
        let http_client = self.http_client.clone();
        let conversation = Arc::clone(&self.conversation);
        let tts_cancel = Arc::clone(&self.tts_cancel);
        
        tokio::spawn(async move {
            let mut audio_buffer: Vec<f32> = Vec::with_capacity(VAD_CHUNK_SAMPLES * 10);
            let mut silence_duration = Duration::ZERO;
            let mut last_speech = Instant::now();
            
            // Connect to Voxtral ASR WebSocket
            let (mut ws_stream, _) = match tokio_tungstenite::connect_async(&config.asr_ws_url).await {
                Ok(conn) => conn,
                Err(e) => {
                    error!("Failed to connect to ASR: {}", e);
                    return;
                }
            };
            
            info!("Connected to Voxtral ASR at {}", config.asr_ws_url);
            
            while let Some(audio_bytes) = rx.recv().await {
                // Convert bytes to f32 PCM
                let samples = bytes_to_f32(&audio_bytes);
                audio_buffer.extend(&samples);
                
                // Process in VAD-sized chunks (256 samples)
                while audio_buffer.len() >= VAD_CHUNK_SAMPLES {
                    let chunk: [f32; VAD_CHUNK_SAMPLES] = 
                        audio_buffer[..VAD_CHUNK_SAMPLES].try_into().unwrap();
                    audio_buffer.drain(..VAD_CHUNK_SAMPLES);
                    
                    // Run VAD
                    let is_speech = {
                        let mut vad = vad.lock().await;
                        vad.is_speech(&chunk)
                    };
                    
                    if is_speech {
                        // Speech detected
                        silence_duration = Duration::ZERO;
                        last_speech = Instant::now();
                        
                        // Update state
                        let current_state = *state.read().await;
                        if current_state == CallState::Speaking {
                            // BARGE-IN: User interrupted bot
                            info!("Barge-in detected! Cancelling TTS...");
                            tts_cancel.lock().await.cancel();
                            *state.write().await = CallState::Processing;
                        } else if current_state == CallState::Listening {
                            *state.write().await = CallState::Processing;
                        }
                        
                        // Stream to ASR
                        let audio_msg = json!({
                            "type": "audio",
                            "data": base64::encode(&chunk.iter()
                                .map(|s| (s * 32767.0) as i16)
                                .flat_map(|s| s.to_le_bytes())
                                .collect::<Vec<_>>())
                        });
                        
                        if let Err(e) = ws_stream.send(
                            tokio_tungstenite::tungstenite::Message::Text(
                                audio_msg.to_string()
                            )
                        ).await {
                            error!("Failed to send to ASR: {}", e);
                        }
                    } else {
                        // Silence detected
                        silence_duration = last_speech.elapsed();
                        
                        // Commit if silence > 600ms and we have pending audio
                        if silence_duration > Duration::from_millis(SILENCE_TIMEOUT_MS) 
                           && *state.read().await == CallState::Processing {
                            info!("Silence timeout, committing transcription...");
                            
                            let commit_msg = json!({"type": "commit"});
                            if let Err(e) = ws_stream.send(
                                tokio_tungstenite::tungstenite::Message::Text(
                                    commit_msg.to_string()
                                )
                            ).await {
                                error!("Failed to send commit: {}", e);
                            }
                            
                            *state.write().await = CallState::Thinking;
                            
                            // Wait for ASR response
                            match timeout(Duration::from_secs(5), ws_stream.next()).await {
                                Ok(Some(Ok(msg))) => {
                                    if let tokio_tungstenite::tungstenite::Message::Text(text) = msg {
                                        if let Ok(response) = serde_json::from_str::<serde_json::Value>(&text) {
                                            if let Some(transcription) = response.get("text").and_then(|t| t.as_str()) {
                                                info!("ASR transcription: {}", transcription);
                                                
                                                // Add to conversation
                                                conversation.write().await.push(json!({
                                                    "role": "user",
                                                    "content": transcription
                                                }));
                                                
                                                // Trigger LLM + TTS pipeline
                                                let tts_cancel = Arc::clone(&tts_cancel);
                                                let conversation = Arc::clone(&conversation);
                                                let config = config.clone();
                                                let http_client = http_client.clone();
                                                let state = Arc::clone(&state);
                                                
                                                tokio::spawn(async move {
                                                    if let Err(e) = process_llm_tts(
                                                        &config,
                                                        &http_client,
                                                        &conversation,
                                                        &state,
                                                        &tts_cancel,
                                                    ).await {
                                                        error!("LLM/TTS processing failed: {}", e);
                                                    }
                                                });
                                            }
                                        }
                                    }
                                }
                                Ok(None) => {
                                    warn!("ASR WebSocket closed");
                                    break;
                                }
                                Ok(Some(Err(e))) => {
                                    error!("ASR WebSocket error: {}", e);
                                }
                                Err(_) => {
                                    warn!("ASR response timeout");
                                }
                            }
                        }
                    }
                }
            }
            
            info!("Ingress loop ended");
        })
    }
    
    /// Egress task: would connect to LiveKit audio track
    fn spawn_egress_task(&self, _tx: mpsc::Sender<Bytes>) -> tokio::task::JoinHandle<()> {
        // Placeholder for LiveKit integration
        tokio::spawn(async move {
            info!("Egress task started");
            // LiveKit audio track integration here
        })
    }
}

/// Process LLM -> TTS pipeline
#[instrument(skip(config, http_client, conversation, state, cancel_token))]
async fn process_llm_tts(
    config: &AgentConfig,
    http_client: &Client,
    conversation: &Arc<RwLock<Vec<serde_json::Value>>>,
    state: &Arc<RwLock<CallState>>,
    cancel_token: &Arc<Mutex<CancellationToken>>,
) -> anyhow::Result<()> {
    *state.write().await = CallState::Thinking;
    
    // Build messages with system prompt
    let messages = {
        let mut msgs = vec![json!({
            "role": "system",
            "content": &config.system_prompt
        })];
        msgs.extend(conversation.read().await.clone());
        msgs
    };
    
    // Call Nemotron LLM
    let llm_request = json!({
        "model": "nvidia/Nemotron-3-Nano-30B",
        "messages": messages,
        "stream": true,
        "max_tokens": 150,
        "temperature": 0.7
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
    
    // Stream LLM tokens and buffer sentences
    let mut sentence_buffer = String::new();
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
                    // Process remaining buffer
                    if !sentence_buffer.is_empty() {
                        generate_tts(&sentence_buffer, config, http_client).await?;
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
                        
                        // Check for sentence end
                        if content.ends_with('.') || content.ends_with('!') || content.ends_with('?') {
                            generate_tts(&sentence_buffer, config, http_client).await?;
                            sentence_buffer.clear();
                        }
                    }
                }
            }
        }
    }
    
    *state.write().await = CallState::Listening;
    Ok(())
}

/// Generate TTS audio from text
#[instrument(skip(text, config, http_client))]
async fn generate_tts(
    text: &str,
    config: &AgentConfig,
    http_client: &Client,
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
                "reference_audio": ref_audio
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
    // (In full implementation, send to LiveKit audio track)
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let _chunk = chunk?;
        // Send to egress channel
        debug!("Received TTS audio chunk: {} bytes", _chunk.len());
    }
    
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
