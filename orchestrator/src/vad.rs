//! Silero VAD v6.2.1 ONNX Implementation
//! 
//! Optimized for 8kHz telephony audio with 256-sample (32ms) chunks.
//! Runs entirely on CPU to preserve GPU VRAM for LLM inference.

use ort::{GraphOptimizationLevel, Session, Value};
use ndarray::{Array1, Array2, Axis};
use std::sync::Arc;
use tracing::{debug, instrument};

/// Silero VAD v6.2.1 configuration for telephony
pub const VAD_SAMPLE_RATE: usize = 8000;
pub const VAD_CHUNK_SAMPLES: usize = 256; // 32ms at 8kHz
pub const VAD_THRESHOLD: f32 = 0.5;
pub const SILENCE_TIMEOUT_MS: u64 = 600; // Commit after 600ms silence

/// Silero VAD session state
pub struct SileroVad {
    session: Arc<Session>,
    threshold: f32,
    /// Hidden state for LSTM (h, c)
    state: Array2<f32>,
    /// Sample rate tensor
    sample_rate: Array1<i64>,
}

impl SileroVad {
    /// Initialize Silero VAD with ONNX model
    /// 
    /// # Arguments
    /// * `model_path` - Path to silero_vad.onnx file
    /// 
    /// # Returns
    /// * `Result<Self, ort::Error>` - Initialized VAD session
    pub fn new(model_path: &str) -> Result<Self, ort::Error> {
        tracing::info!("Loading Silero VAD from: {}", model_path);
        
        let session = Session::builder()?
            .with_optimization_level(GraphOptimizationLevel::Level3)?
            .with_intra_threads(1)? // Single-threaded for cache efficiency
            .commit_from_file(model_path)?;
        
        // Initialize LSTM state: [2, 1, 64] -> (h, c) x batch x hidden
        let state = Array2::<f32>::zeros((2, 64));
        let sample_rate = Array1::from(vec![VAD_SAMPLE_RATE as i64]);
        
        tracing::info!("Silero VAD loaded successfully (threshold: {})", VAD_THRESHOLD);
        
        Ok(Self {
            session: Arc::new(session),
            threshold: VAD_THRESHOLD,
            state,
            sample_rate,
        })
    }
    
    /// Process a single 32ms chunk of 8kHz audio
    /// 
    /// # Arguments
    /// * `pcm_chunk` - 256 samples of f32 PCM audio at 8kHz
    /// 
    /// # Returns
    /// * `f32` - Speech probability (0.0 - 1.0)
    #[instrument(skip(self, pcm_chunk), level = "debug")]
    pub fn process(&mut self, pcm_chunk: &[f32; VAD_CHUNK_SAMPLES]) -> f32 {
        // Convert to ndarray
        let input = Array2::from_shape_vec((1, VAD_CHUNK_SAMPLES), pcm_chunk.to_vec())
            .expect("Valid chunk size");
        
        // Prepare inputs
        let inputs = [
            Value::from_array(input).expect("Valid input tensor"),
            Value::from_array(self.sample_rate.clone()).expect("Valid sample rate"),
            Value::from_array(self.state.clone()).expect("Valid state"),
        ];
        
        // Run inference
        let outputs = match self.session.run(&inputs) {
            Ok(out) => out,
            Err(e) => {
                tracing::error!("VAD inference failed: {}", e);
                return 0.0;
            }
        };
        
        // Extract output
        let speech_prob = outputs[0]
            .try_extract::<f32>()
            .expect("Valid output")
            .view()
            .[[0, 0]];
        
        // Update state
        let new_state = outputs[1]
            .try_extract::<f32>()
            .expect("Valid state");
        self.state.assign(&new_state.view().slice_axis(Axis(0), (0..2).into()).to_owned());
        
        debug!("VAD probability: {:.3}", speech_prob);
        speech_prob
    }
    
    /// Check if chunk contains speech
    /// 
    /// # Arguments
    /// * `pcm_chunk` - 256 samples of f32 PCM audio
    /// 
    /// # Returns
    /// * `bool` - True if speech detected
    pub fn is_speech(&mut self, pcm_chunk: &[f32; VAD_CHUNK_SAMPLES]) -> bool {
        self.process(pcm_chunk) >= self.threshold
    }
    
    /// Reset internal state (call between calls)
    pub fn reset(&mut self) {
        self.state = Array2::<f32>::zeros((2, 64));
        tracing::debug!("VAD state reset");
    }
}

impl Clone for SileroVad {
    fn clone(&self) -> Self {
        Self {
            session: Arc::clone(&self.session),
            threshold: self.threshold,
            state: Array2::<f32>::zeros((2, 64)),
            sample_rate: self.sample_rate.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_vad_chunk_size() {
        // Verify 32ms at 8kHz = 256 samples
        assert_eq!(VAD_CHUNK_SAMPLES, 256);
    }
    
    #[test]
    fn test_silence_detection() {
        // This would require the actual model file
        // Placeholder for integration test
    }
}
