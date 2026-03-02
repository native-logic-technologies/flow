//! Flow - Telephony Orchestrator (Standalone WebSocket Server)

use std::net::SocketAddr;
use std::sync::Arc;
use axum::{
    routing::get,
    Router,
    extract::{ws::{WebSocket, WebSocketUpgrade, Message}, State},
    response::{Response, Html},
};
use tokio::sync::mpsc;
use tracing::{info, warn, error};
use tower_http::cors::CorsLayer;
use futures_util::{SinkExt, StreamExt};

mod agent;
mod audio_pipeline;
mod vad;

use agent::{AgentConfig, TelephonyAgent};

/// Global application state
#[derive(Clone)]
struct AppState {
    config: AgentConfig,
    vad_model_path: String,
}

#[tokio::main(worker_threads = 16)]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("telephony_orchestrator=info".parse()?)
                .add_directive("tower_http=info".parse()?),
        )
        .init();
    
    info!("╔════════════════════════════════════════════════════════════════════╗");
    info!("║  Flow - Telephony Orchestrator (WebSocket Server)                  ║");
    info!("║  Optimized for DGX Spark (GB10) with Blackwell SM121              ║");
    info!("╚════════════════════════════════════════════════════════════════════╝");
    
    let config = load_config()?;
    validate_services(&config).await?;
    
    let vad_model_path = std::env::var("VAD_MODEL_PATH")
        .unwrap_or_else(|_| "./models/silero_vad.onnx".to_string());
    
    info!("Loading Silero VAD from: {}", vad_model_path);
    let _vad = vad::SileroVad::new(&vad_model_path)?;
    info!("✓ VAD loaded successfully");
    
    let state = AppState {
        config,
        vad_model_path,
    };
    
    let app = Router::new()
        .route("/", get(root_handler))
        .route("/health", get(health_handler))
        .route("/web-client", get(web_client_handler))
        .route("/debug", get(debug_handler))
        .route("/ws", get(ws_handler))
        .layer(CorsLayer::permissive())
        .with_state(state);
    
    let bind_addr = std::env::var("BIND_ADDRESS")
        .unwrap_or_else(|_| "0.0.0.0:8080".to_string())
        .parse::<SocketAddr>()?;
    
    info!("Starting WebSocket server on {}", bind_addr);
    info!("Endpoints:");
    info!("  GET /       - Info page");
    info!("  GET /health - Health check");
    info!("  WS  /ws     - WebSocket for audio streaming");
    
    let listener = tokio::net::TcpListener::bind(bind_addr).await?;
    axum::serve(listener, app).await?;
    
    Ok(())
}

async fn root_handler() -> &'static str {
    "Flow Telephony Orchestrator\n\nEndpoints:\n  /health - Health check\n  /web-client - Web UI\n  /ws     - WebSocket for audio streaming\n"
}

async fn web_client_handler() -> Html<&'static str> {
    Html(include_str!("../../web-client/index.html"))
}

async fn debug_handler() -> Html<&'static str> {
    Html(include_str!("../../web-client/debug.html"))
}

async fn health_handler(State(_state): State<AppState>) -> String {
    let mut status = serde_json::json!({
        "status": "healthy",
        "orchestrator": "running",
        "version": env!("CARGO_PKG_VERSION"),
    });
    
    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build() {
        Ok(c) => c,
        Err(_) => return status.to_string(),
    };
    
    let mut services = serde_json::json!({});
    
    match client.get("http://127.0.0.1:8000/health").send().await {
        Ok(r) if r.status().is_success() => {
            services["llm"] = serde_json::json!({"status": "healthy", "port": 8000});
        }
        _ => services["llm"] = serde_json::json!({"status": "unhealthy", "port": 8000}),
    }
    
    match client.get("http://127.0.0.1:8001/health").send().await {
        Ok(r) if r.status().is_success() => {
            services["asr"] = serde_json::json!({"status": "healthy", "port": 8001});
        }
        _ => services["asr"] = serde_json::json!({"status": "unhealthy", "port": 8001}),
    }
    
    match client.get("http://127.0.0.1:8002/health").send().await {
        Ok(r) if r.status().is_success() => {
            services["tts"] = serde_json::json!({"status": "healthy", "port": 8002});
        }
        _ => services["tts"] = serde_json::json!({"status": "unhealthy", "port": 8002}),
    }
    
    status["services"] = services;
    status.to_string()
}

async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> Response {
    ws.on_upgrade(move |socket| handle_websocket(socket, state))
}

async fn handle_websocket(socket: WebSocket, state: AppState) {
    info!("New WebSocket connection established");
    
    let agent = match TelephonyAgent::new(
        state.config.clone(),
        &state.vad_model_path,
    ) {
        Ok(a) => Arc::new(a),
        Err(e) => {
            error!("Failed to create agent: {}", e);
            return;
        }
    };
    
    let (mut sender, mut receiver) = socket.split();
    let (ingress_tx, ingress_rx) = mpsc::channel::<bytes::Bytes>(1000);
    let (egress_tx, mut egress_rx) = mpsc::channel::<bytes::Bytes>(1000);
    let egress_tx_for_text = egress_tx.clone();
    
    // Spawn agent task
    let agent_clone = Arc::clone(&agent);
    let agent_handle = tokio::spawn(async move {
        if let Err(e) = agent_clone.handle_call(ingress_rx, egress_tx).await {
            error!("Agent error: {}", e);
        }
    });
    
    // Spawn egress task
    let egress_handle = tokio::spawn(async move {
        while let Some(audio) = egress_rx.recv().await {
            if sender.send(Message::Binary(audio.to_vec())).await.is_err() {
                break;
            }
        }
    });
    
    // INITIAL GREETING: Spawn a task to play greeting after short delay
    // This ensures egress task is ready and provides immediate audio feedback
    let greeting_tx = egress_tx_for_text.clone();
    let greeting_config = state.config.clone();
    tokio::spawn(async move {
        tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;
        let greeting = "Hey there! I'm Phil. How can I help you today?";
        info!("Playing initial greeting: {}", greeting);
        
        let http_client = reqwest::Client::new();
        if let Err(e) = agent::generate_tts(
            greeting,
            &greeting_config,
            &http_client,
            Some(&greeting_tx),
        ).await {
            error!("Failed to generate greeting: {}", e);
        }
    });
    
    // Handle ingress
    while let Some(msg) = receiver.next().await {
        match msg {
            Ok(Message::Binary(data)) => {
                if ingress_tx.send(bytes::Bytes::from(data)).await.is_err() {
                    break;
                }
            }
            Ok(Message::Text(text)) => {
                if let Ok(control) = serde_json::from_str::<serde_json::Value>(&text) {
                    match control.get("type").and_then(|t| t.as_str()) {
                        Some("ping") => {
                            info!("Received ping from client");
                        }
                        Some("interrupt") => {
                            info!("Client requested interrupt");
                        }
                        Some("text") => {
                            // Text message from client (text mode)
                            if let Some(msg_text) = control.get("text").and_then(|t| t.as_str()) {
                                info!("Received text message: {}", msg_text);
                                
                                // Add to conversation
                                agent.conversation.write().await.push(serde_json::json!({
                                    "role": "user",
                                    "content": msg_text
                                }));
                                
                                // Trigger LLM + TTS pipeline
                                let tts_cancel = Arc::clone(&agent.tts_cancel);
                                let conversation = Arc::clone(&agent.conversation);
                                let config = agent.config.clone();
                                let http_client = agent.http_client.clone();
                                let state = Arc::clone(&agent.state);
                                let egress_tx = egress_tx_for_text.clone();
                                
                                tokio::spawn(async move {
                                    if let Err(e) = agent::process_llm_tts(
                                        &config,
                                        &http_client,
                                        &conversation,
                                        &state,
                                        &tts_cancel,
                                        Some(&egress_tx),
                                    ).await {
                                        error!("LLM/TTS processing failed: {}", e);
                                    }
                                });
                            }
                        }
                        _ => {}
                    }
                }
            }
            Ok(Message::Close(_)) => {
                info!("Client disconnected");
                break;
            }
            Err(e) => {
                error!("WebSocket error: {}", e);
                break;
            }
            _ => {}
        }
    }
    
    // Cleanup
    drop(ingress_tx);
    let _ = agent_handle.await;
    let _ = egress_handle.await;
    
    info!("WebSocket connection closed");
}

fn load_config() -> anyhow::Result<AgentConfig> {
    dotenvy::dotenv().ok();
    
    let voice = if let Ok(voice_file) = std::env::var("TTS_VOICE_FILE") {
        info!("Loading voice file from: {}", voice_file);
        match std::fs::read(&voice_file) {
            Ok(bytes) => {
                let b64 = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, &bytes);
                info!("Voice file loaded: {} bytes -> {} base64 chars", bytes.len(), b64.len());
                Some(b64)
            }
            Err(e) => {
                warn!("Failed to load voice file {}: {}", voice_file, e);
                std::env::var("TTS_VOICE").ok()
            }
        }
    } else {
        std::env::var("TTS_VOICE").ok()
    };
    
    let config = AgentConfig {
        asr_ws_url: std::env::var("ASR_WS_URL")
            .unwrap_or_else(|_| "ws://127.0.0.1:8001/v1/realtime".to_string()),
        llm_url: std::env::var("LLM_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:8000/v1/chat/completions".to_string()),
        tts_url: std::env::var("TTS_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:8002/v1/audio/speech".to_string()),
        voice,
        system_prompt: std::env::var("LLM_SYSTEM_PROMPT")
            .unwrap_or_else(|_| {
                r#"You are Phil, having a casual phone conversation. Give friendly, conversational responses that are at least 30-40 words (2-3 sentences). Short responses don't work well with the voice system, so please be a bit more verbose. Be warm, engaging, and natural."#.to_string()
            }),
    };
    
    info!("Configuration:");
    info!("  ASR: {}", config.asr_ws_url);
    info!("  LLM: {}", config.llm_url);
    info!("  TTS: {}", config.tts_url);
    if config.voice.is_some() {
        info!("  Voice: loaded (base64)");
    } else {
        info!("  Voice: default");
    }
    
    Ok(config)
}

async fn validate_services(_config: &AgentConfig) -> anyhow::Result<()> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()?;
    
    for (name, url) in [
        ("Nemotron LLM", "http://127.0.0.1:8000/health"),
        ("Voxtral ASR", "http://127.0.0.1:8001/health"),
        ("MOSS-TTS", "http://127.0.0.1:8002/health"),
    ] {
        match client.get(url).send().await {
            Ok(resp) if resp.status().is_success() => info!("✓ {} ({})", name, url),
            _ => warn!("✗ {} not responding", name),
        }
    }
    
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[tokio::test]
    async fn test_config_loading() {
        let config = load_config().unwrap();
        assert!(!config.asr_ws_url.is_empty());
        assert!(!config.llm_url.is_empty());
    }
}
