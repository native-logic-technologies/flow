use anyhow::{Context, Result};
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
        const SILENCE_THRESHOLD: u32 = 12; // ~375ms at 30ms frames

        info!("Processing audio track...");

        while let Some(frame) = stream.next().await {
            // Convert frame to f32 at 16kHz
            let samples = Self::convert_frame_to_f32(&frame);

            // Process through VAD
            match processor.process_chunk(&samples) {
                VadResult::Speech(audio) => {
                    silence_frames = 0;
                    speech_buffer.extend(audio);

                    // BARGE-IN: User started speaking while AI is talking
                    let token = cancel_token.lock().await;
                    if !token.is_cancelled() {
                        info!("Barge-in detected! Cancelling AI response");
                        token.cancel();
                        // Clear audio buffer
                        audio_source.clear_buffer();
                    }
                    drop(token);
                }
                VadResult::Silence => {
                    silence_frames += 1;

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
                VadResult::None => {}
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

        // 3. TTS: Persistent WebSocket connection
        self.process_tts_stream(llm_stream, audio_source, cancel_token)
            .await
    }

    /// Transcribe audio using Voxtral-Mini-4B-Realtime via vLLM
    /// Sends multipart form data to vLLM's OpenAI-compatible endpoint
    async fn transcribe_audio(&self, audio_data: Vec<f32>) -> Result<String> {
        // Convert f32 to i16 PCM bytes for Voxtral
        let pcm_bytes: Vec<u8> = audio_data
            .iter()
            .flat_map(|&s| {
                let sample = (s.clamp(-1.0, 1.0) * 32767.0) as i16;
                sample.to_le_bytes()
            })
            .collect();

        // Create multipart form with audio as "in-memory file"
        // This avoids disk I/O and keeps everything in RAM
        let audio_part = reqwest::multipart::Part::bytes(pcm_bytes)
            .file_name("audio.pcm")
            .mime_str("audio/pcm")?;

        let form = reqwest::multipart::Form::new()
            .part("file", audio_part)
            .text("model", "mistralai/Voxtral-Mini-4B-Realtime-2602");

        // Send to Voxtral vLLM endpoint
        let response = self
            .http_client
            .post(format!("{}/v1/audio/transcriptions", self.asr_url))
            .multipart(form)
            .send()
            .await
            .context("Voxtral ASR request failed")?;

        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();
            return Err(anyhow::anyhow!("Voxtral ASR error {}: {}", status, text));
        }

        let result: serde_json::Value = response.json().await?;
        let transcript = result
            .get("text")
            .and_then(|t| t.as_str())
            .unwrap_or("")
            .to_string();
        
        info!("Voxtral transcript: '{}'", transcript);
        Ok(transcript)
    }

    /// Stream LLM tokens from Nemotron
    async fn stream_llm(&self, transcript: &str) -> Result<mpsc::Receiver<String>> {
        let (tx, rx) = mpsc::channel(100);

        let url = format!("{}/v1/chat/completions", self.llm_url);
        let body = json!({
            "model": "/model",
            "messages": [
                {"role": "system", "content": "/no_think\nYou are a helpful voice assistant. Speak naturally with occasional verbal fillers like 'um', 'ahh', 'hmm'. Use backchanneling like 'I see', 'right', 'got it'. Be conversational and warm."},
                {"role": "user", "content": transcript}
            ],
            "stream": true,
            "temperature": 0.0,
            "max_tokens": 150
        });

        let client = self.http_client.clone();

        tokio::spawn(async move {
            let response = match client.post(&url).json(&body).send().await {
                Ok(r) => r,
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

    /// Stream TTS audio to LiveKit with persistent WebSocket
    async fn process_tts_stream(
        &self,
        mut llm_rx: mpsc::Receiver<String>,
        audio_source: NativeAudioSource,
        cancel_token: tokio_util::sync::CancellationToken,
    ) -> Result<()> {
        // Connect to MOSS-TTS WebSocket (persistent for the whole turn)
        let tts_ws_url = format!("{}/ws/tts", self.tts_url);
        let (mut tts_ws, _) = connect_async(&tts_ws_url).await?;

        info!("Connected to TTS WebSocket");

        // Send voice configuration
        let config = json!({
            "voice_id": "phil-conversational",
            "speed": 1.0,
            "temperature": 0.7
        });
        tts_ws.send(Message::Text(config.to_string())).await?;

        let mut sentence_buffer = String::new();
        const MIN_SENTENCE_LEN: usize = 15;

        loop {
            tokio::select! {
                // Check for cancellation (barge-in)
                _ = cancel_token.cancelled() => {
                    info!("Turn cancelled by barge-in");
                    break;
                }

                // Receive LLM tokens
                Some(token) = llm_rx.recv() => {
                    sentence_buffer.push_str(&token);

                    // Check for sentence end
                    if sentence_buffer.len() > MIN_SENTENCE_LEN &&
                       (token.ends_with('.') || token.ends_with('!') ||
                        token.ends_with('?') || token.ends_with(',')) {

                        // Send to TTS
                        let text = std::mem::take(&mut sentence_buffer);
                        if let Err(e) = tts_ws.send(Message::Text(text)).await {
                            error!("TTS send error: {}", e);
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
                                error!("Audio capture error: {}", e);
                            }
                        }
                        Ok(Message::Text(text)) if text == "[DONE]" => {
                            break;
                        }
                        Err(e) => {
                            error!("TTS WebSocket error: {}", e);
                            break;
                        }
                        _ => {}
                    }
                }

                // All senders dropped
                else => break,
            }
        }

        // Flush any remaining text
        if !sentence_buffer.is_empty() {
            let _ = tts_ws.send(Message::Text(sentence_buffer)).await;
        }

        // Close WebSocket gracefully
        let _ = tts_ws.close(None).await;
        info!("TTS stream ended");

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

    info!("Starting LiveKit S2S Orchestrator");
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
