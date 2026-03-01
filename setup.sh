#!/bin/bash
# =============================================================================
# Telephony Stack Master Setup Script
# DGX Spark (GB10) - sm_121 / CUDA 13.0
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║     High-Concurrency 8kHz Telephony Stack Setup                    ║"
echo "║     DGX Spark (GB10) - sm_121 / CUDA 13.0 / NVFP4                 ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Menu
show_menu() {
    echo "Select setup step:"
    echo ""
    echo "  0) Full setup (bootstrap + PyTorch + vLLM + Nemotron)"
    echo "  1) Bootstrap environment only"
    echo "  2) Install PyTorch 2.9.0 (cu130)"
    echo "  3) Install vLLM"
    echo "  4) Download Nemotron-3-Nano-30B"
    echo "  5) Test Nemotron"
    echo "  q) Quit"
    echo ""
}

run_step() {
    local step=$1
    case $step in
        0)
            echo -e "${BLUE}Running full setup...${NC}"
            $SCRIPT_DIR/scripts/bootstrap-environment.sh
            source "$HOME/telephony-stack-env/bin/activate"
            $SCRIPT_DIR/scripts/01-install-pytorch.sh
            $SCRIPT_DIR/scripts/02-install-vllm.sh
            $SCRIPT_DIR/scripts/03-download-nemotron.sh
            $SCRIPT_DIR/scripts/04-test-nemotron.sh
            ;;
        1)
            $SCRIPT_DIR/scripts/bootstrap-environment.sh
            echo ""
            echo -e "${GREEN}✓ Environment bootstrapped${NC}"
            echo "Activate with: source ~/telephony-stack-env/bin/activate"
            ;;
        2)
            source "$HOME/telephony-stack-env/bin/activate"
            $SCRIPT_DIR/scripts/01-install-pytorch.sh
            ;;
        3)
            source "$HOME/telephony-stack-env/bin/activate"
            $SCRIPT_DIR/scripts/02-install-vllm.sh
            ;;
        4)
            source "$HOME/telephony-stack-env/bin/activate"
            $SCRIPT_DIR/scripts/03-download-nemotron.sh
            ;;
        5)
            source "$HOME/telephony-stack-env/bin/activate"
            $SCRIPT_DIR/scripts/04-test-nemotron.sh
            ;;
        q|Q)
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option${NC}"
            ;;
    esac
}

# If argument provided, run that step
if [ -n "$1" ]; then
    run_step "$1"
else
    # Interactive menu
    while true; do
        show_menu
        read -p "Enter choice: " choice
        run_step "$choice"
        echo ""
        read -p "Press enter to continue..."
        clear
    done
fi
