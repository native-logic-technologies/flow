# CleanS2S Logging Guide

## Quick Reference

### View All Services
```bash
cd ~/telephony-stack
./scripts/view-logs.sh all           # Last 50 lines
./scripts/view-logs.sh all -f        # Follow in real-time
./scripts/view-logs.sh all -n 100    # Last 100 lines
```

### View Specific Services

**Nemotron LLM (Port 8000):**
```bash
./scripts/view-logs.sh llm -f
# or
sudo journalctl -u nemotron-llm -f
```

**Voxtral ASR (Port 8001):**
```bash
./scripts/view-logs.sh asr -f
# or
sudo journalctl -u voxtral-asr -f
```

**MOSS-TTS (Port 8002):**
```bash
./scripts/view-logs.sh tts -f
# or
sudo journalctl -u moss-tts -f
```

**Rust Orchestrator (Port 8080):**
```bash
./scripts/view-logs.sh orchestrator -f
# or
sudo journalctl -u telephony-orchestrator -f
```

**Cloudflare Tunnel:**
```bash
./scripts/view-logs.sh tunnel -f
# or
sudo journalctl -u cloudflared-tunnel -f
```

## Advanced Usage

### Filter by Time
```bash
# Last 10 minutes
./scripts/view-logs.sh all --since "10m ago"

# Last hour
./scripts/view-logs.sh all --since "1h ago"

# Since specific time
sudo journalctl -u nemotron-llm --since "2026-03-01 20:00:00"
```

### Filter by Service Combination
```bash
# Just LLM and TTS
sudo journalctl -u nemotron-llm -u moss-tts -f

# Orchestrator and Tunnel
sudo journalctl -u telephony-orchestrator -u cloudflared-tunnel -f
```

### Search for Errors
```bash
# Find errors in all logs
sudo journalctl -u nemotron-llm -u voxtral-asr -u moss-tts -u telephony-orchestrator --grep "ERROR" -n 100

# Find errors in orchestrator
sudo journalctl -u telephony-orchestrator --grep "error" -i -n 50
```

### Export Logs
```bash
# Save last 1000 lines to file
sudo journalctl -u nemotron-llm -n 1000 > ~/nemotron-logs.txt

# Save all logs since service start
sudo journalctl -u telephony-orchestrator --since today > ~/orchestrator-today.txt
```

## Log File Locations

### Systemd Journal (Primary)
All services log to systemd journal:
```bash
# View all telephony stack logs
sudo journalctl -u nemotron-llm -u voxtral-asr -u moss-tts -u telephony-orchestrator -u cloudflared-tunnel
```

### File-Based Logs (Secondary)
Some logs are also written to files:
```bash
# Application logs
ls -la ~/telephony-stack/logs/

# Individual log files
tail -f ~/telephony-stack/logs/nemotron.log
tail -f ~/telephony-stack/logs/moss-tts.log
```

## Real-Time Monitoring

### Watch All Services
```bash
# Terminal 1: Watch all in real-time
./scripts/view-logs.sh all -f

# Terminal 2: Watch just errors
sudo journalctl -u nemotron-llm -u voxtral-asr -u moss-tts -u telephony-orchestrator -p err -f
```

### Monitor Performance
```bash
# Watch GPU utilization (another terminal)
watch -n 1 nvidia-smi

# Watch service status
watch -n 5 'sudo systemctl status nemotron-llm voxtral-asr moss-tts telephony-orchestrator --no-pager'
```

## Common Log Patterns

### LLM (Nemotron)
```
INFO 03-01 20:30:15 [api_server.py:461] Received request
INFO 03-01 20:30:15 [async_llm_engine.py:574] Starting new request
INFO 03-01 20:30:15 [metrics.py:325] First token latency: 0.055s
```

### TTS (MOSS)
```
Loading MOSS-TTS from /home/phil/telephony-stack/models/tts/moss-tts-realtime...
✓ MOSS-TTS-Realtime ready!
Generating TTS for: Hello
Audio chunk: 3840 bytes
```

### Orchestrator
```
INFO telephony_orchestrator: WebSocket connection established
INFO telephony_orchestrator: VAD speech detected
INFO telephony_orchestrator: ASR transcription: Hello
INFO telephony_orchestrator: LLM response received
INFO telephony_orchestrator: TTS audio generated
```

### Cloudflare Tunnel
```
INF Registered tunnel connection
INF Tunnel connection curve preferences
INF Connection established
```

## Troubleshooting

### Service Won't Start
```bash
# Check recent errors
sudo journalctl -u SERVICE_NAME -n 100 --no-pager | grep -i error

# Check full startup log
sudo journalctl -u SERVICE_NAME --since "5m ago"
```

### High Latency
```bash
# Watch LLM and TTS timing
sudo journalctl -u nemotron-llm -u moss-tts -f | grep -E "(latency|time|ms)"
```

### Connection Issues
```bash
# Watch tunnel and orchestrator
sudo journalctl -u cloudflared-tunnel -u telephony-orchestrator -f
```

## Quick Commands Cheat Sheet

```bash
# View last 50 lines of all services
./scripts/view-logs.sh all

# Follow all services in real-time
./scripts/view-logs.sh all -f

# View last 100 LLM lines
./scripts/view-logs.sh llm -n 100

# View TTS logs from last 5 minutes
./scripts/view-logs.sh tts --since "5m ago"

# Search for errors
sudo journalctl -u telephony-orchestrator --grep "error" -i

# Export all logs
sudo journalctl --since today > ~/all-logs-today.txt
```
