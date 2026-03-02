#!/usr/bin/env python3
"""
Quick test for Voxtral ASR server
"""

import requests
import numpy as np
import time

# Generate 1 second of test audio (sine wave)
sample_rate = 16000
duration = 1.0
t = np.linspace(0, duration, int(sample_rate * duration))
# 440Hz tone
audio = np.sin(2 * np.pi * 440 * t) * 0.5
# Convert to 16-bit PCM
pcm_bytes = (audio * 32767).astype(np.int16).tobytes()

print(f"Generated {len(pcm_bytes)} bytes of test audio ({duration}s @ {sample_rate}Hz)")

# Test the server
url = "http://localhost:8001/v1/audio/transcriptions"
print(f"\nSending to {url}...")

start = time.time()
response = requests.post(url, data=pcm_bytes)
elapsed = (time.time() - start) * 1000

print(f"Response time: {elapsed:.1f}ms")
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
