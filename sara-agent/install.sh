#!/bin/bash
#
# Sara Headless Agent Installer
#
# Usage: sudo ./install.sh [OPTIONS]
#
# Options:
#   --token TOKEN     Set the authentication token
#   --backend URL     Set the backend URL (default: https://sara-api.avery.cloud)
#   --uninstall       Remove the agent
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
INSTALL_DIR="/opt/sara-agent"
CONFIG_DIR="/etc/sara-agent"
LOG_FILE="/var/log/sara-agent.log"
SERVICE_NAME="sara-agent"
BACKEND_URL="https://sara-api.avery.cloud"
AUTH_TOKEN=""
UNINSTALL=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --token)
            AUTH_TOKEN="$2"
            shift 2
            ;;
        --backend)
            BACKEND_URL="$2"
            shift 2
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        -h|--help)
            echo "Sara Headless Agent Installer"
            echo ""
            echo "Usage: sudo ./install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --token TOKEN     Set the authentication token"
            echo "  --backend URL     Set the backend URL (default: https://sara-api.avery.cloud)"
            echo "  --uninstall       Remove the agent"
            echo "  -h, --help        Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}This script must be run as root (use sudo)${NC}"
    exit 1
fi

# Uninstall function
uninstall() {
    echo -e "${YELLOW}Uninstalling Sara Headless Agent...${NC}"

    # Stop and disable service
    if systemctl is-active --quiet $SERVICE_NAME; then
        echo "Stopping service..."
        systemctl stop $SERVICE_NAME
    fi

    if systemctl is-enabled --quiet $SERVICE_NAME 2>/dev/null; then
        echo "Disabling service..."
        systemctl disable $SERVICE_NAME
    fi

    # Remove service file
    if [[ -f /etc/systemd/system/$SERVICE_NAME.service ]]; then
        rm /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
    fi

    # Remove installation directory
    if [[ -d $INSTALL_DIR ]]; then
        echo "Removing $INSTALL_DIR..."
        rm -rf $INSTALL_DIR
    fi

    # Ask about config
    read -p "Remove configuration files in $CONFIG_DIR? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf $CONFIG_DIR
    fi

    # Remove user (optional)
    if id "sara-agent" &>/dev/null; then
        read -p "Remove sara-agent user? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            userdel sara-agent
        fi
    fi

    echo -e "${GREEN}Sara Headless Agent uninstalled successfully${NC}"
    exit 0
}

# Handle uninstall
if [[ "$UNINSTALL" == true ]]; then
    uninstall
fi

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║           Sara Headless Agent Installer                    ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check for Python 3
echo -e "${YELLOW}Checking prerequisites...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is required but not installed.${NC}"
    echo "Please install Python 3 first:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "  CentOS/RHEL: sudo yum install python3 python3-pip"
    echo "  Fedora: sudo dnf install python3 python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "  ${GREEN}✓${NC} Python $PYTHON_VERSION found"

# Check for pip
if ! python3 -m pip --version &> /dev/null; then
    echo -e "${YELLOW}Installing pip...${NC}"
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3
fi
echo -e "  ${GREEN}✓${NC} pip available"

# Check for venv
if ! python3 -m venv --help &> /dev/null; then
    echo -e "${RED}python3-venv is required but not installed.${NC}"
    echo "Please install it first:"
    echo "  Ubuntu/Debian: sudo apt install python3-venv"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} venv available"

# Create sara-agent user if it doesn't exist
if ! id "sara-agent" &>/dev/null; then
    echo -e "${YELLOW}Creating sara-agent user...${NC}"
    useradd --system --no-create-home --shell /usr/sbin/nologin sara-agent
    echo -e "  ${GREEN}✓${NC} User created"
else
    echo -e "  ${GREEN}✓${NC} User sara-agent exists"
fi

# Create installation directory
echo -e "${YELLOW}Setting up installation directory...${NC}"
mkdir -p $INSTALL_DIR
mkdir -p $CONFIG_DIR

# Get the script's directory (where the agent files are)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Copy agent files
echo -e "${YELLOW}Installing agent files...${NC}"
cp "$SCRIPT_DIR/main.py" $INSTALL_DIR/
cp "$SCRIPT_DIR/config.py" $INSTALL_DIR/
cp "$SCRIPT_DIR/backend_client.py" $INSTALL_DIR/
cp "$SCRIPT_DIR/metrics.py" $INSTALL_DIR/
cp "$SCRIPT_DIR/requirements.txt" $INSTALL_DIR/

echo -e "  ${GREEN}✓${NC} Agent files installed"

# Create virtual environment
echo -e "${YELLOW}Creating virtual environment...${NC}"
python3 -m venv $INSTALL_DIR/venv
echo -e "  ${GREEN}✓${NC} Virtual environment created"

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
$INSTALL_DIR/venv/bin/pip install --upgrade pip > /dev/null
$INSTALL_DIR/venv/bin/pip install -r $INSTALL_DIR/requirements.txt
echo -e "  ${GREEN}✓${NC} Dependencies installed"

# Prompt for auth token if not provided
if [[ -z "$AUTH_TOKEN" ]]; then
    echo ""
    echo -e "${BLUE}Authentication Setup${NC}"
    echo "To connect this agent to Sara, you need an authentication token."
    echo "You can get this from the Sara web app settings page."
    echo ""
    read -p "Enter your authentication token (or press Enter to skip): " AUTH_TOKEN
fi

# Create config file
echo -e "${YELLOW}Creating configuration...${NC}"
cat > $CONFIG_DIR/config.json << EOF
{
    "backend_url": "$BACKEND_URL",
    "backend_ws_url": "${BACKEND_URL/https/wss}/api/devices/ws",
    "auth_token": "$AUTH_TOKEN",
    "heartbeat_interval": 30,
    "metrics_interval": 60
}
EOF
chmod 600 $CONFIG_DIR/config.json
echo -e "  ${GREEN}✓${NC} Configuration created"

# Create environment file for systemd
cat > $CONFIG_DIR/environment << EOF
SARA_CONFIG_DIR=$CONFIG_DIR
SARA_LOG_FILE=$LOG_FILE
EOF
chmod 600 $CONFIG_DIR/environment

# Create log file
touch $LOG_FILE
chown sara-agent:sara-agent $LOG_FILE

# Set ownership
chown -R sara-agent:sara-agent $INSTALL_DIR
chown -R sara-agent:sara-agent $CONFIG_DIR

# Install systemd service
echo -e "${YELLOW}Installing systemd service...${NC}"
cp "$SCRIPT_DIR/sara-agent.service" /etc/systemd/system/
systemctl daemon-reload
echo -e "  ${GREEN}✓${NC} Service installed"

# Enable and start service
echo -e "${YELLOW}Enabling and starting service...${NC}"
systemctl enable $SERVICE_NAME
systemctl start $SERVICE_NAME
echo -e "  ${GREEN}✓${NC} Service started"

# Check status
sleep 2
if systemctl is-active --quiet $SERVICE_NAME; then
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗"
    echo -e "║         Installation Complete!                              ║"
    echo -e "╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Sara Headless Agent is now running."
    echo ""
    echo "Useful commands:"
    echo "  View status:    sudo systemctl status $SERVICE_NAME"
    echo "  View logs:      sudo journalctl -u $SERVICE_NAME -f"
    echo "  Restart:        sudo systemctl restart $SERVICE_NAME"
    echo "  Stop:           sudo systemctl stop $SERVICE_NAME"
    echo "  Uninstall:      sudo $INSTALL_DIR/install.sh --uninstall"
    echo ""
    echo "Configuration: $CONFIG_DIR/config.json"
    echo "Log file: $LOG_FILE"
    echo ""
    if [[ -z "$AUTH_TOKEN" ]]; then
        echo -e "${YELLOW}Note: No auth token was provided.${NC}"
        echo "Edit $CONFIG_DIR/config.json to add your token, then restart:"
        echo "  sudo systemctl restart $SERVICE_NAME"
    fi
else
    echo ""
    echo -e "${RED}Service failed to start. Check logs:${NC}"
    echo "  sudo journalctl -u $SERVICE_NAME -n 50"
fi
