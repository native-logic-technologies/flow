//! Service clients for LLM, TTS, and ASR

use futures_util::{SinkExt, StreamExt};
use reqwest::Client;
use serde_json::json;
use tokio::sync::mpsc;
use tracing::{info, error};

/// Nemotron LLM client with streaming
pub struct NemotronLLM {
    client: Client,
    url: String,
}

impl NemotronLLM {
    pub fn new(url: &str) -> Self {
        Self {
            client: Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .expect("Failed to create HTTP client"),
            url: url.to_string(),
        }
    }

    /// Stream LLM tokens with optimized settings
    pub async fn generate_stream(
        &self,
        messages: Vec<serde_json::Value>,
    ) -> anyhow::Result<impl futures_util::Stream<Item = anyhow::Result<String>>> {
        let request = json!({
            "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
            "messages": messages,
            "stream": true,
            "max_tokens": 80,
            "temperature": 0.8,
            "top_p": 0.95,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.1,
        });

        let response = self.client
            .post(&self.url)
            .json(&request)
            .send()
            .await?;

        if !response.status().is_success() {
            let error = response.text().await?;
            return Err(anyhow::anyhow!("LLM request failed: {}", error));
        }

        Ok(response.bytes_stream().filter_map(|chunk| async move {
            match chunk {
                Ok(bytes) => {
                    let text = String::from_utf8_lossy(&bytes);
                    // Parse SSE format
                    for line in text.lines() {
                        if let Some(data) = line.strip_prefix("data: ") {
                            if data == "[DONE]" {
                                return None;
                            }
                            if let Ok(json) = serde_json::from_str::<serde_json::Value>(data) {
                                if let Some(content) = json
                                    .get("choices")
                                    .and_then(|c| c.get(0))
                                    .and_then(|c| c.get("delta"))
                                    .and_then(|d| d.get("content"))
                                    .and_then(|c| c.as_str())
                                {
                                    return Some(Ok(content.to_string()));
                                }
                            }
                        }
                    }
                    None
                }
                Err(e) => Some(Err(anyhow::anyhow!("Stream error: {}", e))),
            }
        }))
    }
}

/// MOSS-TTS client with persistent WebSocket
pub struct MossTTS {
    url: String,
}

impl MossTTS {
    pub fn new(url: &str) -> Self {
        Self {
            url: url.to_string(),
        }
    }

    /// Establish persistent WebSocket connection
    pub async fn connect(&self) -> anyhow::Result<TTSWebSocket> {
        use tokio_tungstenite::connect_async;
        use tokio_tungstenite::tungstenite::Message;

        info!("Connecting to MOSS-TTS at {}...", self.url);
        
        let (mut ws_stream, _) = connect_async(&self.url).await?;
        
        // Send init
        let init_msg = json!({
            "type": "init",
            "voice": "default"
        });
        ws_stream.send(Message::Text(init_msg.to_string())).await?;
        
        // Wait for ready
        let ready_msg = ws_stream.next().await.ok_or_else(|| anyhow::anyhow!("TTS closed"))??;
        if let Message::Text(text) = ready_msg {
            let status: serde_json::Value = serde_json::from_str(&text)?;
            if status.get("status").and_then(|s| s.as_str()) == Some("ready") {
                info!("✓ MOSS-TTS connected (persistent)");
            }
        }
        
        Ok(TTSWebSocket { ws: ws_stream })
    }
}

/// Persistent TTS WebSocket handle
pub struct TTSWebSocket {
    ws: tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>,
}

impl TTSWebSocket {
    /// Send text for TTS generation
    pub async fn send_text(&mut self, text: &str) -> anyhow::Result<()> {
        use tokio_tungstenite::tungstenite::Message;
        
        let msg = json!({
            "type": "text",
            "text": text
        });
        self.ws.send(Message::Text(msg.to_string())).await?;
        
        // Send end
        self.ws.send(Message::Text(json!({"type": "end"}).to_string())).await?;
        
        Ok(())
    }

    /// Receive audio chunks
    pub async fn recv_audio(&mut self) -> anyhow::Result<Option<Vec<u8>>> {
        use tokio_tungstenite::tungstenite::Message;
        
        while let Some(msg) = self.ws.next().await {
            match msg? {
                Message::Binary(data) => return Ok(Some(data)),
                Message::Text(text) => {
                    let status: serde_json::Value = serde_json::from_str(&text)?;
                    if status.get("status").and_then(|s| s.as_str()) == Some("complete") {
                        return Ok(None);
                    }
                }
                _ => {}
            }
        }
        
        Ok(None)
    }
}

/// Parakeet ASR client
pub struct ParakeetASR {
    url: String,
}

impl ParakeetASR {
    pub fn new(url: &str) -> Self {
        Self {
            url: url.to_string(),
        }
    }

    /// Stream audio to ASR and get transcriptions
    pub async fn transcribe_stream(
        &self,
        audio_stream: mpsc::Receiver<Vec<u8>>,
    ) -> anyhow::Result<mpsc::Receiver<String>> {
        let (tx, rx) = mpsc::channel(100);
        
        // TODO: Implement WebSocket streaming to ASR
        // For now, placeholder
        tokio::spawn(async move {
            // Process audio and send transcriptions
        });
        
        Ok(rx)
    }
}
