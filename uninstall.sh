#!/bin/bash
# Agent Trajectory Profiler - Uninstall Script

set -e

INSTALL_DIR="$HOME/.local/bin"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    local level=$1
    local message=$2
    local color=""
    case $level in
        "INFO")  color=$BLUE ;;
        "ERROR") color=$RED ;;
        "SUCCESS") color=$GREEN ;;
    esac
    echo -e "${color}[$(date '+%H:%M:%S')] [$level] $message${NC}"
}

log "INFO" "Uninstalling Agent Trajectory Profiler..."

if [[ -f "$INSTALL_DIR/claude-vis" ]]; then
    rm -f "$INSTALL_DIR/claude-vis"
    log "INFO" "Removed $INSTALL_DIR/claude-vis"
else
    log "INFO" "claude-vis not found in $INSTALL_DIR (already removed?)"
fi

if [[ -f "$INSTALL_DIR/agent-vis" ]]; then
    rm -f "$INSTALL_DIR/agent-vis"
    log "INFO" "Removed $INSTALL_DIR/agent-vis"
else
    log "INFO" "agent-vis not found in $INSTALL_DIR (already removed?)"
fi

log "SUCCESS" "Agent Trajectory Profiler uninstalled successfully!"
echo ""
echo "Note: The project directory and uv environment are preserved."
echo "To fully remove, delete the project directory manually."
