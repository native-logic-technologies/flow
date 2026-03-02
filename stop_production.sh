#!/bin/bash
# Stop all production services

echo "Stopping DGX Spark S2S Pipeline..."
echo ""

# Kill tmux sessions
echo "Stopping tmux sessions..."
tmux kill-session -t livekit-orchestrator 2>/dev/null && echo "  ✓ livekit-orchestrator stopped" || echo "  - livekit-orchestrator not running"
tmux kill-session -t voxtral-asr 2>/dev/null && echo "  ✓ voxtral-asr stopped" || echo "  - voxtral-asr not running"
tmux kill-session -t livekit-server 2>/dev/null && echo "  ✓ livekit-server stopped" || echo "  - livekit-server not running"

echo ""
echo "Services stopped."
echo "Note: Nemotron LLM and MOSS-TTS may still be running if started separately."
