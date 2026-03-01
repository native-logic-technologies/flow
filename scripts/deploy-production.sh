#!/bin/bash
# =============================================================================
# Production Deployment Script for CleanS2S Telephony Stack
# =============================================================================
# This script installs systemd services for:
#   - Nemotron LLM (Port 8000)
#   - Voxtral ASR (Port 8001)
#   - MOSS-TTS (Port 8002)
#   - Rust Orchestrator (Port 8080)
#
# Usage: sudo ./deploy-production.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# Create necessary directories
create_directories() {
    log_info "Creating directories..."
    
    # Cache directory
    mkdir -p /tmp/hf_cache
    chown phil:phil /tmp/hf_cache
    
    # Logs directory
    mkdir -p "$PROJECT_ROOT/logs"
    chown phil:phil "$PROJECT_ROOT/logs"
    
    # Models directory (if not exists)
    mkdir -p "$PROJECT_ROOT/models"
    
    log_success "Directories created"
}

# Install systemd services
install_services() {
    log_info "Installing systemd services..."
    
    # Copy service files
    cp "$PROJECT_ROOT/systemd/"*.service /etc/systemd/system/
    
    # Reload systemd
    systemctl daemon-reload
    
    log_success "Services installed"
}

# Enable services to start on boot
enable_services() {
    log_info "Enabling services to start on boot..."
    
    systemctl enable nemotron-llm.service
    systemctl enable voxtral-asr.service
    systemctl enable moss-tts.service
    systemctl enable telephony-orchestrator.service
    
    log_success "Services enabled"
}

# Start services in correct order
start_services() {
    log_info "Starting services (this may take a few minutes)..."
    log_info "  1. Nemotron LLM (model loading: ~2 minutes)"
    
    systemctl start nemotron-llm.service
    
    # Wait for LLM to be ready
    log_info "  Waiting for LLM to be ready..."
    for i in {1..60}; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            log_success "  LLM is ready!"
            break
        fi
        sleep 5
        echo -n "."
    done
    
    log_info "  2. Voxtral ASR"
    systemctl start voxtral-asr.service
    
    log_info "  3. MOSS-TTS"
    systemctl start moss-tts.service
    
    # Wait for TTS
    log_info "  Waiting for TTS to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:8002/health > /dev/null 2>&1; then
            log_success "  TTS is ready!"
            break
        fi
        sleep 2
        echo -n "."
    done
    
    log_info "  4. Rust Orchestrator"
    systemctl start telephony-orchestrator.service
    
    log_success "All services started!"
}

# Check service status
check_status() {
    log_info "Checking service status..."
    echo ""
    
    echo -n "Nemotron LLM:     "
    if systemctl is-active --quiet nemotron-llm; then
        log_success "RUNNING"
    else
        log_error "STOPPED"
    fi
    
    echo -n "Voxtral ASR:      "
    if systemctl is-active --quiet voxtral-asr; then
        log_success "RUNNING"
    else
        log_error "STOPPED"
    fi
    
    echo -n "MOSS-TTS:         "
    if systemctl is-active --quiet moss-tts; then
        log_success "RUNNING"
    else
        log_error "STOPPED"
    fi
    
    echo -n "Orchestrator:     "
    if systemctl is-active --quiet telephony-orchestrator; then
        log_success "RUNNING"
    else
        log_error "STOPPED"
    fi
    
    echo ""
}

# Test health endpoints
test_endpoints() {
    log_info "Testing health endpoints..."
    echo ""
    
    local failed=0
    
    echo -n "LLM (:8000):      "
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        log_success "OK"
    else
        log_error "FAIL"
        failed=1
    fi
    
    echo -n "ASR (:8001):      "
    if curl -s http://localhost:8001/health > /dev/null 2>&1; then
        log_success "OK"
    else
        log_error "FAIL"
        failed=1
    fi
    
    echo -n "TTS (:8002):      "
    if curl -s http://localhost:8002/health > /dev/null 2>&1; then
        log_success "OK"
    else
        log_error "FAIL"
        failed=1
    fi
    
    echo ""
    
    if [[ $failed -eq 0 ]]; then
        log_success "All endpoints healthy!"
    else
        log_warn "Some endpoints are not responding (services may still be starting)"
    fi
}

# Print usage information
print_usage() {
    echo ""
    echo "==================================================================="
    log_success "Production deployment complete!"
    echo "==================================================================="
    echo ""
    echo "Service Management Commands:"
    echo "  sudo systemctl status nemotron-llm    - Check LLM status"
    echo "  sudo systemctl status voxtral-asr     - Check ASR status"
    echo "  sudo systemctl status moss-tts        - Check TTS status"
    echo "  sudo systemctl status telephony-orchestrator - Check orchestrator"
    echo ""
    echo "View Logs:"
    echo "  sudo journalctl -u nemotron-llm -f    - Follow LLM logs"
    echo "  sudo journalctl -u telephony-orchestrator -f - Follow orchestrator logs"
    echo "  sudo journalctl -u nemotron-llm -u voxtral-asr -u moss-tts -u telephony-orchestrator -f - All logs"
    echo ""
    echo "Stop/Start:"
    echo "  sudo systemctl stop nemotron-llm voxtral-asr moss-tts telephony-orchestrator"
    echo "  sudo systemctl start nemotron-llm voxtral-asr moss-tts telephony-orchestrator"
    echo ""
    echo "Endpoints:"
    echo "  LLM:      http://localhost:8000"
    echo "  ASR:      http://localhost:8001"
    echo "  TTS:      http://localhost:8002"
    echo "  Orchestrator WebSocket: ws://localhost:8080"
    echo ""
    echo "Next Steps:"
    echo "  1. Install LiveKit: https://docs.livekit.io/realtime/self-hosting/vm/"
    echo "  2. Configure Cloudflare tunnel for public access"
    echo "  3. Deploy web client"
    echo ""
    echo "See PRODUCTION_DEPLOYMENT_PLAN.md for full details."
    echo "==================================================================="
}

# Main deployment
main() {
    echo "==================================================================="
    echo "     CleanS2S Telephony Stack - Production Deployment"
    echo "==================================================================="
    echo ""
    
    check_root
    create_directories
    install_services
    enable_services
    start_services
    check_status
    test_endpoints
    print_usage
}

# Handle command line arguments
case "${1:-}" in
    --stop)
        log_info "Stopping all services..."
        systemctl stop telephony-orchestrator moss-tts voxtral-asr nemotron-llm 2>/dev/null || true
        log_success "All services stopped"
        ;;
    --restart)
        log_info "Restarting all services..."
        systemctl restart nemotron-llm voxtral-asr moss-tts telephony-orchestrator
        log_success "Services restarted"
        check_status
        ;;
    --status)
        check_status
        test_endpoints
        ;;
    --logs)
        log_info "Showing logs (Ctrl+C to exit)..."
        journalctl -u nemotron-llm -u voxtral-asr -u moss-tts -u telephony-orchestrator -f
        ;;
    *)
        main
        ;;
esac
