//! Voxtral ASR Client
//! 
//! Proper integration with Voxtral-Mini-4B-Realtime via vLLM's WebSocket API.
//! Uses the /v1/realtime endpoint with proper event formatting.

use bytes::Bytes;
use futures_util::{SinkExt, StreamExt};
use serde_json::json;
use tokio::sync::mpsc;
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{debug, error, info, warn};

/// ASR client for Voxtral
pub struct VoxtralASRClient {
    url: String,
}

impl VoxtralASRClient {
    pub fn new(url: String) -> Self {
        Self { url }
    }

    /// Connect to ASR and start processing audio
    /// 
    /// Returns channels for:
    /// - audio_input: Send audio bytes to ASR
    /// - transcription_output: Receive transcriptions from ASR
    pub async fn connect(
        &self,
    ) -> anyhow::Result<(mpsc::Sender<Bytes>, mpsc::Receiver<String>)> {
        let (ws_stream, _) = connect_async(&self.url).await?;
        info!("Connected to Voxtral ASR at {}", self.url);

        let (mut ws_sender, mut ws_receiver) = ws_stream.split();
        
        // Channels for audio input and transcription output
        let (audio_tx, mut audio_rx) = mpsc::channel::<Bytes>(100);
        let (transcription_tx, transcription_rx) = mpsc::channel::<String>(10);

        // Send session initialization
        let session_init = json!({
            "type": "session.update",
            "session": {
                "modalities": ["text"],
                "input_audio_format": "pcm",
                "input_audio_transcription": {
                    "model": "voxtral-mini-4b-realtime"
                }
            }
        });
        ws_sender.send(Message::Text(session_init.to_string())).await?;

        // Spawn task to handle WebSocket communication
        let transcription_tx_clone = transcription_tx.clone();
        tokio::spawn(async move {
            let mut audio_buffer: Vec<u8> = Vec::new();
            
            loop {
                tokio::select! {
                    // Receive audio from channel
                    Some(audio) = audio_rx.recv() => {
                        audio_buffer.extend_from_slice(&audio);
                        
                        // Send audio in chunks
                        if audio_buffer.len() >= 3200 {  // ~200ms @ 8kHz 16-bit
                            let audio_b64 = base64::encode(&audio_buffer);
                            
                            let audio_event = json!({
                                "type": "input_audio_buffer.append",
                                "audio": audio_b64
                            });
                            
                            if let Err(e) = ws_sender.send(Message::Text(audio_event.to_string())).await {
                                error!("Failed to send audio: {}", e);
                                break;
                            }
                            
                            audio_buffer.clear();
                        }
                    }
                    
                    // Receive messages from WebSocket
                    Some(msg) = ws_receiver.next() => {
                        match msg {
                            Ok(Message::Text(text)) => {
                                if let Ok(event) = serde_json::from_str::<serde_json::Value>(&text) {
                                    match event.get("type").and_then(|t| t.as_str()) {
                                        Some("session.created") => {
                                            info!("ASR session created");
                                        }
                                        Some("input_audio_buffer.committed") => {
                                            // Commit the buffer and request transcription
                                            let commit = json!({
                                                "type": "input_audio_buffer.commit"
                                            });
                                            let _ = ws_sender.send(Message::Text(commit.to_string())).await;
                                        }
                                        Some("conversation.item.input_audio_transcription.completed") => {
                                            // Transcription received
                                            if let Some(text) = event.get("transcript").and_then(|t| t.as_str()) {
                                                info!("ASR transcription: {}", text);
                                                let _ = transcription_tx_clone.send(text.to_string()).await;
                                            }
                                        }
                                        Some("error") => {
                                            error!("ASR error: {:?}", event);
                                        }
                                        _ => {
                                            debug!("ASR event: {:?}", event);
                                        }
                                    }
                                }
                            }
                            Ok(Message::Close(_)) => {
                                info!("ASR WebSocket closed");
                                break;
                            }
                            Err(e) => {
                                error!("ASR WebSocket error: {}", e);
                                break;
                            }
                            _ => {}
                        }
                    }
                    
                    else => break,
                }
            }
        });

        Ok((audio_tx, transcription_rx))
    }
}

/// Simple ASR that uses HTTP instead of WebSocket
/// Fallback for when WebSocket is not available
pub struct HTTPASRClient {
    url: String,
    http_client: reqwest::Client,
}

impl HTTPASRClient {
    pub fn new(url: String) -> Self {
        Self {
            url,
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(10))
                .build()
                .unwrap(),
        }
    }

    /// Transcribe audio buffer
    pub async fn transcribe(&self, audio: &[u8]) -> anyhow::Result<String> {
        // For now, return empty to indicate ASR not properly configured
        // In production, this would call the actual ASR endpoint
        warn!("HTTP ASR not fully implemented, audio received: {} bytes", audio.len());
        Ok(String::new())
    }
}
