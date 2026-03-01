# Flow

High-performance voice AI stack for NVIDIA DGX Spark (GB10), optimized for real-time telephony applications.

## Overview

Flow is a complete speech-to-speech AI pipeline combining state-of-the-art NVIDIA and open-source models:

- **LLM**: Nemotron-3-Nano-30B-A3B-NVFP4 (vLLM) - Port 8000
- **ASR**: Voxtral-Mini-4B-Realtime (vLLM) - Port 8001  
- **TTS**: MOSS-TTS-Realtime (Native PyTorch) - Port 8002

## Quick Start

```bash
# Clone this repository
git clone https://github.com/native-logic-technologies/flow.git
cd flow

# Install dependencies (DGX Spark with CUDA 13.0)
./scripts/install-moss-tts.sh

# Start all services
./scripts/start-nemotron.sh      # Terminal 1
./scripts/start-voxtral-asr.sh   # Terminal 2  
./scripts/start-moss-tts-native.sh  # Terminal 3
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DGX Spark GB10 (128GB VRAM)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ Port 8000        │  │ Port 8001        │  │ Port 8002        │          │
│  │ Nemotron-3-Nano  │  │ Voxtral-Mini-4B  │  │ MOSS-TTS-Realtime│          │
│  │ Framework: vLLM  │  │ Framework: vLLM  │  │ Framework: PyTorch│         │
│  │ Quant: modelopt_fp4                  │  │ Dtype: bfloat16  │          │
│  │ Memory: 20% (16GB)                   │  │ Memory: 15% (12GB)│          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
│                                                                              │
│  Free: ~55% (~55GB) for concurrent calls                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Documentation

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Complete setup instructions
- [MOSS_TTS_DEPLOYMENT_STATUS.md](MOSS_TTS_DEPLOYMENT_STATUS.md) - TTS-specific documentation

## Dependencies

- NVIDIA DGX Spark (GB10) with CUDA 13.0
- Python 3.12
- PyTorch 2.9.1+cu130
- vLLM v0.16.0 (compiled from source)

## License

[Add your license here]

## Contributing

[Add contribution guidelines]
