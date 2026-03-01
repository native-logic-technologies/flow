//! Flow - LiveKit Telephony Orchestrator
//! 
//! High-performance Rust orchestrator for real-time speech-to-speech AI
//! on NVIDIA DGX Spark (GB10).
//!
//! Architecture:
//! - VAD: Silero v6.2.1 (ONNX, CPU)
//! - ASR: Voxtral-Mini-4B (vLLM, Port 8001)
//! - LLM: Nemotron-3-Nano (vLLM, Port 8000)
//! - TTS: MOSS-TTS-Realtime (PyTorch, Port 8002)

use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::{info, warn, error};

mod agent;
mod vad;

use agent::{AgentConfig, TelephonyAgent};

/// Tokio runtime configuration optimized for DGX Spark
/// 
/// Reserve CPU cores for:
/// - vLLM Python processes (ports 8000, 8001)
/// - MOSS-TTS FastAPI (port 8002)
/// - This orchestrator (remaining cores)
#[tokio::main(worker_threads = 16)]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("telephony_orchestrator=info".parse()?)
                .add_directive("tokio_tungstenite=warn".parse()?),
        )
        .init();
    
    info!("╔════════════════════════════════════════════════════════════════════╗");
    info!("║  Flow - LiveKit Telephony Orchestrator                             ║");
    info!("║  Optimized for DGX Spark (GB10) with Blackwell SM121              ║");
    info!("╚════════════════════════════════════════════════════════════════════╝");
    info!("");
    
    // Load configuration
    let config = load_config()?;
    
    // Validate backend services
    info!("Validating backend services...");
    validate_services(&config).await?;
    
    // Initialize VAD
    let vad_model_path = std::env::var("VAD_MODEL_PATH")
        .unwrap_or_else(|_| "./models/silero_vad.onnx".to_string());
    
    info!("Loading Silero VAD from: {}", vad_model_path);
    let _vad = vad::SileroVad::new(&vad_model_path)?;
    info!("✓ VAD loaded successfully");
    
    // Start LiveKit server (placeholder for actual integration)
    info!("Starting LiveKit integration...");
    start_livekit_server(config).await?;
    
    Ok(())
}

/// Load configuration from environment or config file
fn load_config() -> anyhow::Result<AgentConfig> {
    dotenvy::dotenv().ok();
    
    // Load voice setting
    let voice = if let Ok(voice_file) = std::env::var("TTS_VOICE_FILE") {
        // Load reference audio from file for zero-shot cloning
        match std::fs::read(&voice_file) {
            Ok(bytes) => {
                let b64 = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, bytes);
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
                "You are a helpful voice assistant for telephone conversations. \
                 Keep responses concise and natural.".to_string()
            }),
    };
    
    info!("Configuration loaded:");
    info!("  ASR WebSocket: {}", config.asr_ws_url);
    info!("  LLM HTTP: {}", config.llm_url);
    info!("  TTS HTTP: {}", config.tts_url);
    if config.voice.is_some() {
        info!("  Voice: Using zero-shot voice cloning (reference audio provided)");
    }
    
    Ok(config)
}

/// Validate backend services are accessible
async fn validate_services(_config: &AgentConfig) -> anyhow::Result<()> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()?;
    
    // Check Nemotron LLM
    match client.get("http://127.0.0.1:8000/health").send().await {
        Ok(resp) if resp.status().is_success() => {
            info!("✓ Nemotron LLM (Port 8000)");
        }
        _ => {
            warn!("✗ Nemotron LLM not responding on port 8000");
        }
    }
    
    // Check Voxtral ASR
    match client.get("http://127.0.0.1:8001/health").send().await {
        Ok(resp) if resp.status().is_success() => {
            info!("✓ Voxtral ASR (Port 8001)");
        }
        _ => {
            warn!("✗ Voxtral ASR not responding on port 8001");
        }
    }
    
    // Check MOSS-TTS
    match client.get("http://127.0.0.1:8002/health").send().await {
        Ok(resp) if resp.status().is_success() => {
            info!("✓ MOSS-TTS (Port 8002)");
        }
        _ => {
            warn!("✗ MOSS-TTS not responding on port 8002");
        }
    }
    
    Ok(())
}

/// Start LiveKit server integration
/// 
/// In production, this would integrate with LiveKit's SFU
/// For now, it's a placeholder showing the architecture
async fn start_livekit_server(config: AgentConfig) -> anyhow::Result<()> {
    info!("LiveKit server integration starting...");
    
    // Create agent instance
    let agent = Arc::new(TelephonyAgent::new(
        config,
        &std::env::var("VAD_MODEL_PATH").unwrap_or_else(|_| "./models/silero_vad.onnx".to_string()),
    )?);
    
    // Create channels for audio flow
    // ingress: LiveKit -> Agent (caller's voice)
    let (_ingress_tx, ingress_rx) = mpsc::channel::<bytes::Bytes>(1000);
    
    // egress: Agent -> LiveKit (bot's voice)
    let (egress_tx, mut egress_rx) = mpsc::channel::<bytes::Bytes>(1000);
    
    // Spawn the agent
    let agent_clone = Arc::clone(&agent);
    tokio::spawn(async move {
        if let Err(e) = agent_clone.handle_call(ingress_rx, egress_tx).await {
            error!("Agent error: {}", e);
        }
    });
    
    // Spawn egress audio consumer
    tokio::spawn(async move {
        while let Some(audio) = egress_rx.recv().await {
            // In production: send to LiveKit audio track
            tracing::debug!("Egress audio: {} bytes", audio.len());
        }
    });
    
    // Keep main thread alive
    info!("Orchestrator running. Press Ctrl+C to stop.");
    tokio::signal::ctrl_c().await?;
    info!("Shutting down...");
    
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
        assert!(!config.tts_url.is_empty());
    }
}
