use anyhow::{Context, Result};
use base64;
use futures::{SinkExt, StreamExt};
use libwebrtc::audio_stream::native::NativeAudioStream;
use libwebrtc::audio_source::{native::NativeAudioSource, RtcAudioSource};
use libwebrtc::prelude::{AudioFrame, AudioSourceOptions};
use livekit::prelude::*;
use livekit::options::TrackPublishOptions;
use livekit_api::access_token::{AccessToken, VideoGrants};
use reqwest::Client as HttpClient;
use serde_json::json;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{error, info};

mod audio;
use audio::{AudioProcessor, VadResult};

/// LiveKit S2S Agent for DGX Spark
#[derive(Clone)]
struct S2SAgent {
    http_client: HttpClient,
    llm_url: String,
    asr_url: String,
    tts_url: String,
}

impl S2SAgent {
    fn new() -> Self {
        Self {
            http_client: HttpClient::new(),
            llm_url: std::env::var("LLM_URL").unwrap_or_else(|_| "http://localhost:8000".into()),
            asr_url: std::env::var("ASR_URL").unwrap_or_else(|_| "http://localhost:8001".into()),
            tts_url: std::env::var("TTS_URL").unwrap_or_else(|_| "ws://localhost:8002".into()),
        }
    }

    /// Process a single room connection
    async fn process_room(
        &self,
        room: Room,
        mut room_events: mpsc::UnboundedReceiver<RoomEvent>,
    ) -> Result<()> {
        info!("Starting S2S agent in room: {}", room.name());

        // Setup audio source for agent output
        let audio_source = NativeAudioSource::new(
            AudioSourceOptions {
                echo_cancellation: true,
                noise_suppression: true,
                auto_gain_control: true,
            },
            24000, // MOSS-TTS outputs 24kHz
            1,
            100, // queue_size_ms
        );

        let track = LocalAudioTrack::create_audio_track("agent-mic", RtcAudioSource::Native(audio_source.clone()));

        // Publish audio track
        room.local_participant()
            .publish_track(
                LocalTrack::Audio(track),
                TrackPublishOptions::default(),
            )
            .await?;

        info!("Audio track published");

        // Cancellation token for barge-in
        let cancel_token = Arc::new(Mutex::new(tokio_util::sync::CancellationToken::new()));

        // Process room events
        while let Some(event) = room_events.recv().await {
            match event {
                RoomEvent::TrackSubscribed {
                    track: RemoteTrack::Audio(audio_track),
                    publication: _,
                    participant: _,
                } => {
                    info!("Subscribed to audio track: {}", audio_track.sid());

                    // Create audio stream from track
                    let stream = NativeAudioStream::new(audio_track.rtc_track(), 16000, 1);

                    // Spawn processing task that owns the stream
                    let agent = self.clone();
                    let source = audio_source.clone();
                    let token = cancel_token.clone();

                    tokio::spawn(async move {
                        if let Err(e) = agent.process_audio_track(stream, source, token).await {
                            error!("Audio track processing error: {}", e);
                        }
                    });
                }
                _ => {}
            }
        }

        Ok(())
    }

    /// Process audio from a track
    async fn process_audio_track(
        &self,
        mut stream: NativeAudioStream,
        audio_source: NativeAudioSource,
        cancel_token: Arc<Mutex<tokio_util::sync::CancellationToken>>,
    ) -> Result<()> {
        let mut processor = AudioProcessor::new(16000);
        let mut speech_buffer: Vec<f32> = Vec::new();
        let mut silence_frames: u32 = 0;
        let mut speech_frames: u32 = 0;
        const SILENCE_THRESHOLD: u32 = 12; // ~375ms at 30ms frames
        const BARGE_IN_SPEECH_FRAMES: u32 = 8; // ~240ms of continuous speech before barge-in

        info!("Processing audio track...");

        while let Some(frame) = stream.next().await {
            // Convert frame to f32 at 16kHz
            let samples = Self::convert_frame_to_f32(&frame);

            // Process through VAD
            match processor.process_chunk(&samples) {
                VadResult::Speech(audio) => {
                    silence_frames = 0;
                    speech_frames += 1;
                    speech_buffer.extend(audio);

                    // BARGE-IN: User started speaking while AI is talking
                    // Require multiple consecutive speech frames to avoid false triggers
                    let token = cancel_token.lock().await;
                    if !token.is_cancelled() && speech_frames >= BARGE_IN_SPEECH_FRAMES {
                        info!("Barge-in detected! Cancelling AI response");
                        token.cancel();
                        // Clear audio buffer
                        audio_source.clear_buffer();
                    }
                    drop(token);
                }
                VadResult::Silence => {
                    silence_frames += 1;
                    speech_frames = 0;

                    // End of speech detected
                    if silence_frames > SILENCE_THRESHOLD && !speech_buffer.is_empty() {
                        info!("End of speech detected, {} samples", speech_buffer.len());

                        // Take ownership of buffer
                        let audio_data = std::mem::take(&mut speech_buffer);

                        // Reset cancel token for new turn
                        let new_token = tokio_util::sync::CancellationToken::new();
                        {
                            let mut token_guard = cancel_token.lock().await;
                            *token_guard = new_token.clone();
                        }

                        // Spawn AI response pipeline
                        let agent = self.clone();
                        let source = audio_source.clone();
                        tokio::spawn(async move {
                            if let Err(e) = agent.process_turn(audio_data, source, new_token).await {
                                error!("Turn processing error: {}", e);
                            }
                        });

                        silence_frames = 0;
                    }
                }
                _ => {}
            }
        }

        Ok(())
    }

    /// Process a single conversational turn: ASR -> LLM -> TTS
    async fn process_turn(
        &self,
        audio_data: Vec<f32>,
        audio_source: NativeAudioSource,
        cancel_token: tokio_util::sync::CancellationToken,
    ) -> Result<()> {
        // 1. ASR: Convert audio to text
        let transcript = self.transcribe_audio(audio_data).await?;
        if transcript.trim().is_empty() {
            return Ok(());
        }
        info!("User said: {}", transcript);

        // 2. LLM: Stream tokens
        let llm_stream = self.stream_llm(&transcript).await?;

        // 3. TTS: Persistent WebSocket connection with TRUE TOKEN-LEVEL STREAMING
        self.process_tts_stream(llm_stream, audio_source, cancel_token)
            .await
    }

    /// Transcribe audio using Voxtral-Mini-4B-Realtime via WebSocket Realtime API
    /// Streams audio chunks and receives transcription tokens in real-time
    async fn transcribe_audio(&self, audio_data: Vec<f32>) -> Result<String> {
        use tokio_tungstenite::tungstenite::Message as WsMessage;
        use base64::Engine;
        
        // Connect to Voxtral Realtime WebSocket endpoint
        let ws_url = self.asr_url.replace("http://", "ws://").replace("https://", "wss://");
        let realtime_url = format!("{}/v1/realtime", ws_url);
        
        info!("Connecting to Voxtral Realtime API at {}", realtime_url);
        
        let (mut ws_stream, _) = connect_async(&realtime_url)
            .await
            .context("Failed to connect to Voxtral Realtime API")?;
        
        // Wait for session.created
        let session_id = match ws_stream.next().await {
            Some(Ok(WsMessage::Text(text))) => {
                let msg: serde_json::Value = serde_json::from_str(&text)?;
                if msg.get("type").and_then(|t| t.as_str()) == Some("session.created") {
                    let id = msg.get("id").and_then(|i| i.as_str()).unwrap_or("unknown").to_string();
                    info!("Voxtral session created: {}", id);
                    id
                } else {
                    return Err(anyhow::anyhow!("Expected session.created, got: {}", text));
                }
            }
            Some(Err(e)) => return Err(anyhow::anyhow!("WebSocket error: {}", e)),
            _ => return Err(anyhow::anyhow!("Unexpected WebSocket response")),
        };
        
        // CRITICAL: Voxtral Realtime API requires model at TOP LEVEL, not in session
        // The session.turn_detection must be null for manual commit mode
        let session_update = json!({
            "type": "session.update",
            "model": "/home/phil/telephony-stack/models/asr/voxtral-mini-4b-realtime",
            "session": {
                "modalities": ["text"],
                "input_audio_format": "pcm16",
                "turn_detection": null
            }
        });
        
        ws_stream.send(WsMessage::Text(session_update.to_string())).await?;
        info!("Sent session.update with model");
        
        // vLLM Realtime API does NOT send back session.updated - validation is internal
        // Just proceed immediately to sending audio after a small delay
        tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
        
        // Convert f32 audio to PCM16 bytes
        let pcm_bytes: Vec<u8> = audio_data
            .iter()
            .flat_map(|&s| {
                let sample = (s.clamp(-1.0, 1.0) * 32767.0) as i16;
                sample.to_le_bytes()
            })
            .collect();
        
        // Send audio in chunks (80ms = 1280 samples at 16kHz = 2560 bytes)
        const CHUNK_SAMPLES: usize = 1280;
        const CHUNK_BYTES: usize = CHUNK_SAMPLES * 2; // 16-bit = 2 bytes per sample
        
        info!("Streaming {} bytes of audio to Voxtral", pcm_bytes.len());
        
        for chunk in pcm_bytes.chunks(CHUNK_BYTES) {
            let audio_msg = json!({
                "type": "input_audio_buffer.append",
                "audio": base64::engine::general_purpose::STANDARD.encode(chunk)
            });
            ws_stream.send(WsMessage::Text(audio_msg.to_string())).await?;
        }
        
        // Signal end of audio input - this triggers transcription automatically
        // Use final: false to start generation (final: true just stops without generating)
        let commit_msg = json!({
            "type": "input_audio_buffer.commit",
            "final": false
        });
        ws_stream.send(WsMessage::Text(commit_msg.to_string())).await?;
        info!("Sent input_audio_buffer.commit (triggering transcription)");
        
        // Collect transcription
        let mut transcript_parts: Vec<String> = Vec::new();
        let timeout = tokio::time::Duration::from_secs(10);
        let deadline = tokio::time::Instant::now() + timeout;
        
        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            
            match tokio::time::timeout(remaining, ws_stream.next()).await {
                Ok(Some(Ok(WsMessage::Text(text)))) => {
                    let msg: serde_json::Value = match serde_json::from_str(&text) {
                        Ok(v) => v,
                        Err(_) => continue,
                    };
                    
                    let msg_type = msg.get("type").and_then(|t| t.as_str());
                    
                    // Debug: log all event types
                    info!("Voxtral event: {:?}", msg_type);
                    
                    match msg_type {
                        Some("transcription.delta") => {
                            if let Some(delta) = msg.get("delta").and_then(|d| d.as_str()) {
                                if !delta.is_empty() {
                                    transcript_parts.push(delta.to_string());
                                    info!("Transcription delta: '{}'", delta);
                                } else {
                                    info!("Empty delta received");
                                }
                            }
                        }
                        Some("transcription.done") => {
                            let text = msg.get("text").and_then(|t| t.as_str()).unwrap_or("");
                            info!("Transcription done: '{}'", text);
                            break;
                        }
                        Some("error") => {
                            error!("Voxtral error: {:?}", msg);
                            break;
                        }
                        _ => {
                            // Log other events for debugging
                            if let Some(t) = msg_type {
                                info!("Other Voxtral event: {} - {:?}", t, msg);
                            }
                        }
                    }
                }
                Ok(Some(Ok(_))) => {
                    // Ignore other WebSocket message types
                    continue;
                }
                Ok(Some(Err(e))) => {
                    error!("WebSocket error: {}", e);
                    break;
                }
                Ok(None) => break,
                Err(_) => {
                    info!("Voxtral transcription timeout");
                    break;
                }
            }
        }
        
        // Close WebSocket gracefully
        let _ = ws_stream.close(None).await;
        
        let transcript = transcript_parts.join("").trim().to_string();
        info!("Final Voxtral transcript (session: {}): '{}'", session_id, transcript);
        
        Ok(transcript)
    }

    /// Stream LLM tokens from Nemotron
    async fn stream_llm(&self, transcript: &str) -> Result<mpsc::Receiver<String>> {
        let (tx, rx) = mpsc::channel(256); // Larger buffer for streaming

        let url = format!("{}/v1/chat/completions", self.llm_url);
        let body = json!({
            "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
            "messages": [
                {"role": "system", "content": "/no_think\nYou are a helpful voice assistant. Speak naturally with occasional verbal fillers like 'um', 'ahh', 'hmm'. Use backchanneling like 'I see', 'right', 'got it'. Be conversational and warm."},
                {"role": "user", "content": transcript}
            ],
            "stream": true,
            "temperature": 0.0,
            "max_tokens": 150
        });

        info!("LLM: Sending request for transcript: '{}'", transcript);
        let client = self.http_client.clone();

        tokio::spawn(async move {
            let response = match client.post(&url).json(&body).send().await {
                Ok(r) => {
                    info!("LLM: Got response, status: {}", r.status());
                    r
                }
                Err(e) => {
                    error!("LLM request failed: {}", e);
                    return;
                }
            };

            let mut stream = response.bytes_stream();
            let mut buffer = String::new();

            while let Some(chunk) = stream.next().await {
                match chunk {
                    Ok(bytes) => {
                        buffer.push_str(&String::from_utf8_lossy(&bytes));

                        // Process SSE lines
                        while let Some(pos) = buffer.find('\n') {
                            let line = buffer.split_off(pos + 1);
                            let current = std::mem::replace(&mut buffer, line);
                            let trimmed = current.trim();

                            if trimmed.starts_with("data: ") {
                                let data = &trimmed[6..];
                                if data == "[DONE]" {
                                    break;
                                }

                                // Parse SSE JSON
                                if let Ok(json) = serde_json::from_str::<serde_json::Value>(data) {
                                    if let Some(content) = json
                                        .get("choices")
                                        .and_then(|c| c.get(0))
                                        .and_then(|c| c.get("delta"))
                                        .and_then(|d| d.get("content"))
                                        .and_then(|c| c.as_str())
                                    {
                                        info!("LLM token: '{}'", content);
                                        if tx.send(content.to_string()).await.is_err() {
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Err(e) => {
                        error!("LLM stream error: {}", e);
                        break;
                    }
                }
            }
        });

        Ok(rx)
    }

    /// Stream TTS audio to LiveKit with TRUE TOKEN-LEVEL STREAMING
    /// Sends each LLM token to TTS immediately for <500ms E2E latency
    async fn process_tts_stream(
        &self,
        mut llm_rx: mpsc::Receiver<String>,
        audio_source: NativeAudioSource,
        cancel_token: tokio_util::sync::CancellationToken,
    ) -> Result<()> {
        // Connect to MOSS-TTS WebSocket (persistent for the whole turn)
        let tts_ws_url = format!("{}/ws/tts", self.tts_url);
        let (mut tts_ws, _) = connect_async(&tts_ws_url).await?;

        info!("TTS: Connected to WebSocket for token-level streaming");

        // Send init message for streaming protocol
        let init_msg = json!({
            "type": "init",
            "voice": "phil"
        });
        tts_ws.send(Message::Text(init_msg.to_string())).await?;
        info!("TTS: Sent init message");

        // "Comma-Level Chunking" with "Trailing Buffer" - Industry Standard S2S
        // 25-character sliding window with punctuation triggers for optimal
        // balance between latency (<500ms) and prosody (natural intonation)
        let mut token_buffer = String::new();
        const FLUSH_SIZE: usize = 25;  // "Golden Ratio" - enough for prosody, small enough for speed
        const FLUSH_TRIGGERS: &[char] = &[',', '.', '!', '?', ';', ':'];  // Punctuation triggers
        const FLUSH_TIMEOUT_MS: u64 = 50;  // Flush after N milliseconds if no punctuation

        // Create interval for periodic flushing
        let mut flush_interval = tokio::time::interval(
            tokio::time::Duration::from_millis(FLUSH_TIMEOUT_MS)
        );
        flush_interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

        loop {
            tokio::select! {
                // Check for cancellation (barge-in)
                _ = cancel_token.cancelled() => {
                    info!("TTS: Turn cancelled by barge-in");
                    break;
                }

                // Receive LLM tokens - "Comma-Level Chunking" for optimal prosody
                Some(token) = llm_rx.recv() => {
                    info!("TTS: Received token: '{}'", token);
                    
                    // Check if token contains punctuation trigger
                    let should_flush = token.ends_with(FLUSH_TRIGGERS) ||
                                      FLUSH_TRIGGERS.iter().any(|&p| token.contains(p));
                    
                    token_buffer.push_str(&token);

                    // Flush on: (1) Punctuation, (2) Buffer size threshold, or (3) Timeout
                    if should_flush || token_buffer.len() >= FLUSH_SIZE {
                        let text = std::mem::take(&mut token_buffer);
                        let token_msg = json!({
                            "type": "token",
                            "text": text
                        });
                        info!("TTS: Streaming chunk ({} chars): '{}'", text.len(), text);
                        if let Err(e) = tts_ws.send(Message::Text(token_msg.to_string())).await {
                            error!("TTS: Send error: {}", e);
                            break;
                        }
                    }
                }

                // Periodic flush for low-latency with small token accumulation
                _ = flush_interval.tick() => {
                    if !token_buffer.is_empty() {
                        let text = std::mem::take(&mut token_buffer);
                        let token_msg = json!({
                            "type": "token",
                            "text": text
                        });
                        info!("TTS: Periodic flush: '{}'", text);
                        if let Err(e) = tts_ws.send(Message::Text(token_msg.to_string())).await {
                            error!("TTS: Send error: {}", e);
                            break;
                        }
                    }
                }

                // Receive TTS audio and send to LiveKit
                Some(msg) = tts_ws.next() => {
                    match msg {
                        Ok(Message::Binary(audio)) => {
                            // Convert bytes to i16 samples
                            let samples: Vec<i16> = audio
                                .chunks_exact(2)
                                .map(|chunk| i16::from_le_bytes([chunk[0], chunk[1]]))
                                .collect();
                            let samples_per_channel = samples.len() as u32;
                            let frame = AudioFrame {
                                data: samples.into(),
                                sample_rate: 24000,
                                num_channels: 1,
                                samples_per_channel,
                            };

                            if let Err(e) = audio_source.capture_frame(&frame).await {
                                error!("TTS: Audio capture error: {}", e);
                            }
                        }
                        Ok(Message::Text(text)) => {
                            // Check for completion signal (JSON format)
                            if let Ok(json) = serde_json::from_str::<serde_json::Value>(&text) {
                                if json.get("type").and_then(|t| t.as_str()) == Some("complete") {
                                    info!("TTS: Received completion signal");
                                    break;
                                }
                            }
                        }
                        Ok(Message::Close(_)) => {
                            info!("TTS: WebSocket closed by server");
                            break;
                        }
                        Err(e) => {
                            error!("TTS: WebSocket error: {}", e);
                            break;
                        }
                        _ => {}
                    }
                }

                // All senders dropped - LLM stream ended
                else => {
                    info!("TTS: LLM stream ended");
                    break;
                }
            }
        }

        // Send any remaining buffered tokens
        if !token_buffer.is_empty() {
            let final_msg = json!({
                "type": "token",
                "text": token_buffer
            });
            let _ = tts_ws.send(Message::Text(final_msg.to_string())).await;
        }

        // Send end signal to TTS
        let end_msg = json!({"type": "end"});
        let _ = tts_ws.send(Message::Text(end_msg.to_string())).await;
        info!("TTS: Sent end signal");

        // Wait a bit for final audio to come back
        let timeout = tokio::time::Duration::from_millis(500);
        let deadline = tokio::time::Instant::now() + timeout;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() {
                break;
            }

            match tokio::time::timeout(remaining, tts_ws.next()).await {
                Ok(Some(Ok(Message::Binary(audio)))) => {
                    let samples: Vec<i16> = audio
                        .chunks_exact(2)
                        .map(|chunk| i16::from_le_bytes([chunk[0], chunk[1]]))
                        .collect();
                    let samples_per_channel = samples.len() as u32;
                    let frame = AudioFrame {
                        data: samples.into(),
                        sample_rate: 24000,
                        num_channels: 1,
                        samples_per_channel,
                    };
                    let _ = audio_source.capture_frame(&frame).await;
                }
                Ok(Some(Ok(Message::Text(text)))) => {
                    if let Ok(json) = serde_json::from_str::<serde_json::Value>(&text) {
                        if json.get("type").and_then(|t| t.as_str()) == Some("complete") {
                            break;
                        }
                    }
                }
                _ => break,
            }
        }

        // Close WebSocket gracefully
        let _ = tts_ws.close(None).await;
        info!("TTS: Stream ended");

        Ok(())
    }

    /// Convert audio frame to f32 samples
    fn convert_frame_to_f32(frame: &AudioFrame) -> Vec<f32> {
        frame
            .data
            .iter()
            .map(|&sample| sample as f32 / 32768.0)
            .collect()
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt::init();

    // Load environment
    dotenvy::dotenv().ok();

    let api_key = std::env::var("LIVEKIT_API_KEY")
        .unwrap_or_else(|_| "APIQp4vjmCjrWQ9".to_string());
    let api_secret = std::env::var("LIVEKIT_API_SECRET")
        .unwrap_or_else(|_| "PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l".to_string());
    let ws_url = std::env::var("LIVEKIT_WS_URL")
        .unwrap_or_else(|_| "ws://localhost:7880".to_string());
    let room_name = std::env::var("ROOM_NAME").unwrap_or_else(|_| "dgx-spark-room".to_string());

    info!("Starting LiveKit S2S Orchestrator (Token-Level Streaming)");
    info!("Connecting to LiveKit at: {}", ws_url);
    info!("Joining room: {}", room_name);

    // Generate access token
    let token = AccessToken::with_api_key(&api_key, &api_secret)
        .with_identity("dgx-agent")
        .with_name("DGX S2S Agent")
        .with_grants(VideoGrants {
            room_join: true,
            room: room_name.clone(),
            can_publish: true,
            can_subscribe: true,
            can_publish_data: true,
            ..Default::default()
        })
        .to_jwt()?;

    // Connect to room - returns (Room, RoomEvent receiver)
    let (room, room_events) = Room::connect(&ws_url, &token, RoomOptions::default()).await?;
    info!("Connected to room: {}", room.name());

    // Start agent
    let agent = S2SAgent::new();
    agent.process_room(room, room_events).await?;

    Ok(())
}
