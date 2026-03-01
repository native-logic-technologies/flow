#!/bin/bash
# =============================================================================
# Log Viewer for CleanS2S Telephony Stack
# =============================================================================
# Usage: ./view-logs.sh [service] [options]
#   service: all, llm, asr, tts, orchestrator, tunnel, or specific
#   options: -f (follow), -n NUM (lines), --since TIME
#
# Examples:
#   ./view-logs.sh all              # Show all recent logs
#   ./view-logs.sh llm -f           # Follow LLM logs in real-time
#   ./view-logs.sh tts -n 100       # Show last 100 TTS lines
#   ./view-logs.sh orchestrator -f  # Follow orchestrator logs
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Service mapping
get_service_name() {
    case "$1" in
        llm|nemotron|8000)
            echo "nemotron-llm"
            ;;
        asr|voxtral|8001)
            echo "voxtral-asr"
            ;;
        tts|moss|8002)
            echo "moss-tts"
            ;;
        orchestrator|orch|8080)
            echo "telephony-orchestrator"
            ;;
        tunnel|cloudflared|cf)
            echo "cloudflared-tunnel"
            ;;
        all|*)
            echo "all"
            ;;
    esac
}

# Show help
show_help() {
    echo -e "${BLUE}CleanS2S Log Viewer${NC}"
    echo ""
    echo "Usage: $0 [service] [options]"
    echo ""
    echo "Services:"
    echo "  all, llm, asr, tts, orchestrator, tunnel"
    echo "  (or use port numbers: 8000, 8001, 8002, 8080)"
    echo ""
    echo "Options:"
    echo "  -f, --follow          Follow logs in real-time"
    echo "  -n NUM                Show last NUM lines (default: 50)"
    echo "  --since TIME          Show logs since TIME (e.g., '10m ago', '1h ago')"
    echo "  --help                Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 all -f                    # Follow all services"
    echo "  $0 llm -n 100               # Last 100 LLM lines"
    echo "  $0 orchestrator -f          # Follow orchestrator"
    echo "  $0 tts --since '5m ago'     # TTS logs from last 5 min"
    echo "  $0 all --since '1h ago' -n 200  # All logs from last hour"
}

# Parse arguments
SERVICE="all"
LINES="50"
FOLLOW=""
SINCE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--follow)
            FOLLOW="-f"
            shift
            ;;
        -n)
            LINES="$2"
            shift 2
            ;;
        --since)
            SINCE="--since $2"
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}"
            show_help
            exit 1
            ;;
        *)
            SERVICE=$(get_service_name "$1")
            shift
            ;;
    esac
done

# Build journalctl command
if [ "$SERVICE" = "all" ]; then
    SERVICES="nemotron-llm voxtral-asr moss-tts telephony-orchestrator cloudflared-tunnel"
    echo -e "${BLUE}Viewing logs for all services...${NC}"
else
    SERVICES="$SERVICE"
    echo -e "${BLUE}Viewing logs for $SERVICE...${NC}"
fi

# Show status first
echo ""
echo -e "${YELLOW}Current Status:${NC}"
for svc in $SERVICES; do
    status=$(sudo systemctl is-active "$svc" 2>/dev/null || echo "unknown")
    if [ "$status" = "active" ]; then
        echo -e "  ${GREEN}✓${NC} $svc: $status"
    else
        echo -e "  ${RED}✗${NC} $svc: $status"
    fi
done
echo ""

# Run journalctl
if [ -n "$FOLLOW" ]; then
    echo -e "${GREEN}Following logs (Ctrl+C to exit)...${NC}"
    echo ""
fi

cmd="sudo journalctl -u $SERVICES $SINCE -n $LINES $FOLLOW --no-hostname"
echo -e "${BLUE}Command: $cmd${NC}"
echo ""
eval $cmd
