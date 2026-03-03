//! LiveKit S2S Agent - Production Voice AI Orchestrator
//! 
//! Architecture:
//! - LiveKit handles WebRTC, A/V sync, and client connections
//! - Persistent WebSocket connections to TTS (Port 8002)
//! - Streaming LLM (Nemotron on Port 8000)
//! - Native Parakeet ASR (will run in venv, port 50051)
//!
//! Optimized for DGX Spark (GB10) with Blackwell SM121

use livekit::prelude::*;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex, RwLock};
use tokio::time::{sleep, Duration};
use tracing::{info, warn, error};
use futures_util::{SinkExt, StreamExt};
use bytes::Bytes;

mod services;
use services::{NemotronLLM, MossTTS, ParakeetASR};

/// Configuration for the S2S pipeline
#[derive(Clone)]
struct PipelineConfig {
    llm_url: String,
    tts_url: String,
    asr_url: String,
}

impl Default for PipelineConfig {
    fn default() -> Self {
        Self {
            llm_url: "http://127.0.0.1:8000/v1/chat/completions".to_string(),
            tts_url: "ws://127.0.0.1:8002/ws/tts".to_string(),
            asr_url: "ws://127.0.0.1:8001/v1/realtime".to_string(),
        }
    }
}

/// Per-call state with persistent connections
struct CallSession {
    room: Arc<Room>,
    config: PipelineConfig,
    
    // Persistent WebSocket to TTS (key for low latency!)
    tts_ws: Arc<Mutex<Option<tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>>>>,
    
    // Audio channels
    audio_tx: mpsc::Sender<Bytes>,
    audio_rx: Arc<Mutex<mpsc::Receiver<Bytes>>>,
    
    // Conversation history
    conversation: Arc<RwLock<Vec<serde_json::Value>>>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("livekit_s2s_agent=info".parse()?)
                .add_directive("livekit=info".parse()?),
        )
        .init();

    info!("╔════════════════════════════════════════════════════════════════════╗");
    info!("║  LiveKit S2S Agent - Production Voice AI                          ║");
    info!("║  DGX Spark (GB10) with Blackwell SM121                            ║");
    info!("╚════════════════════════════════════════════════════════════════════╝");

    // Load configuration from environment
    let config = PipelineConfig::default();
    
    // Verify services are healthy
    verify_services(&config).await?;

    // Connect to LiveKit server
    let url = std::env::var("LIVEKIT_URL")
        .unwrap_or_else(|_| "ws://localhost:7880".to_string());
    let api_key = std::env::var("LIVEKIT_API_KEY")
        .unwrap_or_else(|_| "devkey".to_string());
    let api_secret = std::env::var("LIVEKIT_API_SECRET")
        .unwrap_or_else(|_| "secret".to_string());

    info!("Connecting to LiveKit at {}...", url);
    
    let token = livekit::AccessToken::with_api_key(&api_key, &api_secret)
        .with_identity("s2s-agent")
        .with_name("Voice AI Agent")
        .with_grants(VideoGrants {
            room_join: true,
            room: "voice-room".to_string(),
            ..Default::default()
        })
        .to_jwt()?;

    let (room, mut rx) = Room::connect(&url, &token, RoomOptions::default()).await?;
    let room = Arc::new(room);

    info!("✓ Connected to LiveKit room: voice-room");
    info!("Waiting for participants...");

    // Handle room events
    while let Some(event) = rx.recv().await {
        match event {
            RoomEvent::ParticipantConnected(participant) => {
                info!("Participant connected: {}", participant.identity());
                
                // Spawn new call session
                let room_clone = room.clone();
                let config_clone = config.clone();
                tokio::spawn(async move {
                    if let Err(e) = handle_call(room_clone, participant, config_clone).await {
                        error!("Call handling error: {}", e);
                    }
                });
            }
            RoomEvent::ParticipantDisconnected(participant) => {
                info!("Participant disconnected: {}", participant.identity());
            }
            RoomEvent::ConnectionStateChanged(state) => {
                info!("Connection state: {:?}", state);
            }
            _ => {}
        }
    }

    Ok(())
}

/// Handle a complete call session with persistent connections
async fn handle_call(
    room: Arc<Room>,
    participant: RemoteParticipant,
    config: PipelineConfig,
) -> anyhow::Result<()> {
    info!("Starting call session for {}", participant.identity());

    // Create audio channels
    let (audio_tx, audio_rx) = mpsc::channel::<Bytes>(1000);
    
    // Initialize conversation
    let conversation = Arc::new(RwLock::new(vec![
        serde_json::json!({
            "role": "system",
            "content": "You are Phil having a natural phone conversation. Use occasional fillers like 'um', 'ahh', 'hmm' and backchanneling. Keep responses SHORT (1-2 sentences)."
        })
    ]));

    // ESTABLISH PERSISTENT TTS WEBSOCKET (Key optimization!)
    info!("Opening persistent TTS WebSocket...");
    let tts_ws = connect_tts_websocket(&config.tts_url).await?;
    let tts_ws = Arc::new(Mutex::new(Some(tts_ws)));

    // Publish audio track to participant
    let audio_track = LocalAudioTrack::create_audio_track(
        "agent-audio",
        AudioSource::default(),
    );
    room.local_participant()
        .publish_track(
            LocalTrack::Audio(audio_track.clone()),
            TrackPublishOptions::default(),
        )
        .await?;

    // Spawn audio forwarding task
    let tts_ws_clone = tts_ws.clone();
    tokio::spawn(async move {
        if let Err(e) = forward_audio_to_participant(
            audio_rx,
            audio_track,
            tts_ws_clone,
        ).await {
            error!("Audio forwarding error: {}", e);
        }
    });

    // Send greeting
    let greeting = "Hey there! I'm Phil. How can I help you today?";
    info!("Playing greeting: {}", greeting);
    
    // Generate greeting audio via persistent WebSocket
    generate_tts_audio(greeting, &tts_ws, &audio_tx).await?;

    // Main conversation loop
    loop {
        // Wait for user audio (simplified - in production use LiveKit's audio callbacks)
        sleep(Duration::from_millis(100)).await;
        
        // TODO: Integrate Parakeet ASR here
        // For now, break after greeting for testing
        sleep(Duration::from_secs(5)).await;
        break;
    }

    info!("Call session ended for {}", participant.identity());
    Ok(())
}

/// Connect to TTS WebSocket once and keep it open
async fn connect_tts_websocket(
    url: &str,
) -> anyhow::Result<tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>> {
    use tokio_tungstenite::connect_async;
    use tokio_tungstenite::tungstenite::Message;

    info!("Connecting to TTS WebSocket at {}...", url);
    
    let (mut ws_stream, _) = connect_async(url).await?;
    
    // Send init message
    let init_msg = serde_json::json!({
        "type": "init",
        "voice": "default"
    });
    ws_stream.send(Message::Text(init_msg.to_string())).await?;
    
    // Wait for ready
    let ready_msg = ws_stream.next().await.ok_or_else(|| anyhow::anyhow!("TTS closed"))??;
    if let Message::Text(text) = ready_msg {
        let status: serde_json::Value = serde_json::from_str(&text)?;
        if status.get("status").and_then(|s| s.as_str()) == Some("ready") {
            info!("✓ TTS WebSocket ready (persistent connection)");
        }
    }
    
    Ok(ws_stream)
}

/// Generate TTS audio using persistent WebSocket
async fn generate_tts_audio(
    text: &str,
    tts_ws: &Arc<Mutex<Option<tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>>>>,
    audio_tx: &mpsc::Sender<Bytes>,
) -> anyhow::Result<()> {
    use tokio_tungstenite::tungstenite::Message;
    
    let mut ws = tts_ws.lock().await;
    let ws = ws.as_mut().ok_or_else(|| anyhow::anyhow!("TTS not connected"))?;
    
    // Send text
    let msg = serde_json::json!({
        "type": "text",
        "text": text
    });
    ws.send(Message::Text(msg.to_string())).await?;
    
    // Send end
    ws.send(Message::Text(serde_json::json!({"type": "end"}).to_string())).await?;
    
    // Receive audio chunks
    while let Some(msg) = ws.next().await {
        match msg? {
            Message::Binary(data) => {
                audio_tx.send(Bytes::from(data)).await?;
            }
            Message::Text(text) => {
                let status: serde_json::Value = serde_json::from_str(&text)?;
                if status.get("status").and_then(|s| s.as_str()) == Some("complete") {
                    break;
                }
            }
            _ => {}
        }
    }
    
    Ok(())
}

/// Forward audio from TTS to LiveKit participant
async fn forward_audio_to_participant(
    audio_rx: Arc<Mutex<mpsc::Receiver<Bytes>>>,
    audio_track: LocalAudioTrack,
    tts_ws: Arc<Mutex<Option<tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>>>>,
) -> anyhow::Result<()> {
    let mut rx = audio_rx.lock().await;
    
    while let Some(audio_chunk) = rx.recv().await {
        // Send to LiveKit (WebRTC handles A/V sync)
        // TODO: Implement proper audio frame handling
        info!("Forwarding {} bytes of audio", audio_chunk.len());
    }
    
    Ok(())
}

/// Verify all services are healthy
async fn verify_services(config: &PipelineConfig) -> anyhow::Result<()> {
    let client = reqwest::Client::new();
    
    // Check LLM
    info!("Verifying Nemotron LLM...");
    let resp = client.get("http://127.0.0.1:8000/health").send().await?;
    if resp.status().is_success() {
        info!("✓ Nemotron LLM");
    }
    
    // Check TTS
    info!("Verifying MOSS-TTS...");
    let resp = client.get("http://127.0.0.1:8002/health").send().await?;
    if resp.status().is_success() {
        info!("✓ MOSS-TTS");
    }
    
    Ok(())
}
