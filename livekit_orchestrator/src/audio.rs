/// Audio processing module for VAD and optional denoising
use std::collections::VecDeque;

pub enum VadResult {
    Speech(Vec<f32>),
    Silence,
    None,
}

/// Simple energy-based VAD (Silero VAD can be added as feature)
pub struct AudioProcessor {
    sample_rate: u32,
    frame_size: usize,
    ring_buffer: VecDeque<f32>,
    energy_threshold: f32,
    speech_frames: u32,
    silence_frames: u32,
}

impl AudioProcessor {
    pub fn new(sample_rate: u32) -> Self {
        // 30ms frame size
        let frame_size = (sample_rate as usize * 30) / 1000;
        
        Self {
            sample_rate,
            frame_size,
            ring_buffer: VecDeque::with_capacity(frame_size * 2),
            energy_threshold: 0.01, // Adjust based on noise floor
            speech_frames: 0,
            silence_frames: 0,
        }
    }

    /// Process incoming audio chunk and return VAD decision
    pub fn process_chunk(&mut self, samples: &[f32]) -> VadResult {
        self.ring_buffer.extend(samples.iter().copied());
        
        let mut result = VadResult::None;
        
        while self.ring_buffer.len() >= self.frame_size {
            // Extract frame
            let frame: Vec<f32> = self.ring_buffer.drain(0..self.frame_size).collect();
            
            // Calculate RMS energy
            let energy: f32 = frame.iter().map(|s| s * s).sum::<f32>() / frame.len() as f32;
            let rms = energy.sqrt();
            
            // VAD decision with hysteresis
            if rms > self.energy_threshold {
                self.speech_frames += 1;
                self.silence_frames = 0;
                
                // Require 3 consecutive speech frames to trigger
                if self.speech_frames >= 3 {
                    result = VadResult::Speech(frame);
                }
            } else {
                self.silence_frames += 1;
                
                // Require 10 consecutive silence frames to trigger end
                if self.silence_frames >= 10 {
                    self.speech_frames = 0;
                    result = VadResult::Silence;
                }
            }
        }
        
        result
    }

    /// Set custom energy threshold for different environments
    pub fn set_threshold(&mut self, threshold: f32) {
        self.energy_threshold = threshold;
    }
}

/// Resample audio using linear interpolation
pub fn resample_linear(input: &[f32], input_rate: u32, output_rate: u32) -> Vec<f32> {
    if input_rate == output_rate {
        return input.to_vec();
    }
    
    let ratio = output_rate as f32 / input_rate as f32;
    let output_len = (input.len() as f32 * ratio) as usize;
    let mut output = Vec::with_capacity(output_len);
    
    for i in 0..output_len {
        let src_idx = i as f32 / ratio;
        let idx = src_idx as usize;
        let frac = src_idx - idx as f32;
        
        let a = input.get(idx).copied().unwrap_or(0.0);
        let b = input.get(idx.saturating_add(1).min(input.len() - 1)).copied().unwrap_or(a);
        
        output.push(a + (b - a) * frac);
    }
    
    output
}

/// Convert f32 samples (-1.0 to 1.0) to i16 bytes
pub fn f32_to_i16_bytes(samples: &[f32]) -> Vec<u8> {
    samples
        .iter()
        .flat_map(|&s| {
            let clamped = s.clamp(-1.0, 1.0);
            let i16_sample = (clamped * 32767.0) as i16;
            i16_sample.to_le_bytes().to_vec()
        })
        .collect()
}

/// Convert i16 bytes to f32 samples
pub fn i16_bytes_to_f32(bytes: &[u8]) -> Vec<f32> {
    bytes
        .chunks_exact(2)
        .map(|chunk| {
            let sample = i16::from_le_bytes([chunk[0], chunk[1]]);
            sample as f32 / 32768.0
        })
        .collect()
}
