#!/bin/bash

# Simple Cron Setup Script for Jarvis Mode
# This script only sets up the cron jobs for an existing Jarvis installation
# 
# Usage: ./setup_cron_only.sh

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}

# Default configuration
JARVIS_HOME="/home/david/jarvis"
JARVIS_USER=$(whoami)
BACKEND_DIR="$JARVIS_HOME/backend"
LOGS_DIR="$JARVIS_HOME/logs"

# Get configuration from user
get_config() {
    echo "=== Jarvis Cron Setup ==="
    echo
    
    read -p "Jarvis installation directory [$JARVIS_HOME]: " input
    JARVIS_HOME="${input:-$JARVIS_HOME}"
    
    read -p "Database URL [postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub]: " input
    DB_URL="${input:-postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub}"
    
    read -p "Solo user ID [1]: " input
    SOLO_USER_ID="${input:-1}"
    
    read -p "Daily brief time (HH:MM) [06:30]: " input
    BRIEF_TIME="${input:-06:30}"
    
    # Parse time
    BRIEF_HOUR=$(echo $BRIEF_TIME | cut -d: -f1)
    BRIEF_MIN=$(echo $BRIEF_TIME | cut -d: -f2)
    
    echo
    echo "Configuration:"
    echo "  Jarvis Home: $JARVIS_HOME"
    echo "  Database: $DB_URL"
    echo "  Solo User ID: $SOLO_USER_ID"
    echo "  Daily Brief: $BRIEF_TIME (${BRIEF_MIN} ${BRIEF_HOUR} * * *)"
    echo
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        error "Setup cancelled"
    fi
}

check_installation() {
    log "Checking Jarvis installation..."
    
    if [[ ! -d "$JARVIS_HOME" ]]; then
        error "Jarvis directory not found: $JARVIS_HOME"
    fi
    
    if [[ ! -f "$JARVIS_HOME/scripts/daily_brief_simple.py" ]]; then
        error "Daily brief script not found: $JARVIS_HOME/scripts/daily_brief_simple.py"
    fi
    
    # Create logs directory if it doesn't exist
    mkdir -p "$LOGS_DIR"
    
    log "✓ Installation check passed"
}

test_daily_brief() {
    log "Testing daily brief generation..."
    
    cd "$JARVIS_HOME"
    
    # Test the daily brief script
    JARVIS_MODE=true SOLO_USER_ID="$SOLO_USER_ID" DATABASE_URL="$DB_URL" python3 scripts/test_daily_brief.py
    
    if [[ $? -eq 0 ]]; then
        log "✓ Daily brief test passed"
    else
        error "✗ Daily brief test failed"
    fi
}

setup_cron() {
    log "Setting up cron jobs..."
    
    # Backup existing crontab
    crontab -l > /tmp/current_crontab 2>/dev/null || touch /tmp/current_crontab
    
    # Create new crontab with Jarvis jobs
    cat > /tmp/jarvis_crontab << EOF
# Existing cron jobs
$(cat /tmp/current_crontab | grep -v "daily_brief_simple.py" | grep -v "# Jarvis")

# Jarvis Daily Brief Generation
$BRIEF_MIN $BRIEF_HOUR * * * JARVIS_MODE=true SOLO_USER_ID=$SOLO_USER_ID DATABASE_URL="$DB_URL" /usr/bin/python3 $JARVIS_HOME/scripts/daily_brief_simple.py >> $LOGS_DIR/daily_brief.log 2>&1

# Jarvis Log Cleanup (weekly)
0 3 * * 0 /usr/bin/find $LOGS_DIR -name "*.log" -mtime +7 -delete
EOF
    
    # Install new crontab
    crontab /tmp/jarvis_crontab
    
    # Cleanup
    rm -f /tmp/current_crontab /tmp/jarvis_crontab
    
    log "✓ Cron jobs installed"
}

verify_cron() {
    log "Verifying cron setup..."
    
    # Check if cron service is running
    if pgrep -x "cron" > /dev/null || pgrep -x "crond" > /dev/null; then
        log "✓ Cron service is running"
    else
        warn "Cron service may not be running"
    fi
    
    # Show installed cron jobs
    log "Installed cron jobs:"
    crontab -l | grep -E "(daily_brief|Jarvis)" || warn "No Jarvis cron jobs found"
}

print_summary() {
    echo
    echo "=== Setup Complete ==="
    echo
    echo "Daily brief will be generated at $BRIEF_TIME every day"
    echo "Logs will be written to: $LOGS_DIR/daily_brief.log"
    echo
    echo "To test manually:"
    echo "  cd $JARVIS_HOME"
    echo "  JARVIS_MODE=true SOLO_USER_ID=$SOLO_USER_ID DATABASE_URL=\"$DB_URL\" python3 scripts/daily_brief_simple.py"
    echo
    echo "To view logs:"
    echo "  tail -f $LOGS_DIR/daily_brief.log"
    echo
    echo "To check cron jobs:"
    echo "  crontab -l"
    echo
}

main() {
    get_config
    check_installation
    test_daily_brief
    setup_cron
    verify_cron
    print_summary
}

main "$@"