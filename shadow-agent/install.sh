#!/bin/bash
# Shadow Agent macOS/Linux Installer
# Usage: bash install.sh [API_URL] [API_TOKEN]

set -e

API_URL="${1:-http://10.185.1.180:8000}"
API_TOKEN="${2:-}"

echo "🕵️  Shadow Mode Agent Installer for macOS/Linux"
echo "================================================"
echo ""

# Install directory
INSTALL_DIR="$HOME/.sara/shadow-agent"
mkdir -p "$INSTALL_DIR"

echo "📦 Installing Shadow Agent to: $INSTALL_DIR"
echo ""

# Check for Python
echo "🐍 Checking for Python..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8+ first:"
    echo "   macOS: brew install python3"
    echo "   Linux: sudo apt install python3 python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "✅ Python found: $PYTHON_VERSION"

# Check for pip
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 not found. Installing..."
    python3 -m ensurepip --upgrade
fi

# Create agent script
echo ""
echo "📋 Creating agent script..."

cat > "$INSTALL_DIR/shadow_agent.py" << 'AGENT_SCRIPT'
import os
import sys
import time
import json
import logging
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import subprocess

# Configuration
API_BASE_URL = os.getenv('SARA_API_URL', 'http://10.185.1.180:8000')
API_TOKEN = os.getenv('SARA_API_TOKEN', '')
POLL_INTERVAL = 5

# Setup logging
LOG_FILE = Path.home() / '.sara' / 'shadow-agent.log'
LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ShadowAgentMac:
    def __init__(self):
        self.session_id = None
        self.last_app = None
        self.last_title = None
        self.last_url = None

    def get_active_session(self):
        try:
            headers = {'Authorization': f'Bearer {API_TOKEN}'} if API_TOKEN else {}
            response = requests.get(f'{API_BASE_URL}/shadow/active', headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                active = data.get('active_session')
                if active:
                    return active.get('session_id')
            return None
        except Exception as e:
            logger.debug(f"No active session: {e}")
            return None

    def send_event(self, event_type, app_name, metadata):
        if not self.session_id:
            return
        try:
            headers = {'Authorization': f'Bearer {API_TOKEN}'} if API_TOKEN else {}
            payload = {'event_type': event_type, 'app_name': app_name, 'metadata': metadata}
            response = requests.post(
                f'{API_BASE_URL}/shadow/{self.session_id}/event',
                json=payload, headers=headers, timeout=5
            )
            if response.status_code == 201:
                logger.info(f"📤 Sent {event_type} event: {app_name}")
        except Exception as e:
            logger.error(f"Error sending event: {e}")

    def get_active_window_mac(self):
        """Get active window on macOS using AppleScript"""
        try:
            script = '''
            tell application "System Events"
                set frontApp to name of first application process whose frontmost is true
                tell process frontApp
                    set frontWindow to name of front window
                end tell
            end tell
            return frontApp & "|" & frontWindow
            '''
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            if result.returncode == 0:
                output = result.stdout.strip()
                if '|' in output:
                    app, title = output.split('|', 1)
                    return app.strip(), title.strip()
            return None, None
        except Exception as e:
            logger.error(f"Error getting active window: {e}")
            return None, None

    def get_browser_url_mac(self, app_name):
        """Get current browser URL on macOS using AppleScript"""
        browser_scripts = {
            'Google Chrome': 'tell application "Google Chrome" to get URL of active tab of front window',
            'Safari': 'tell application "Safari" to get URL of current tab of front window',
            'Firefox': 'tell application "Firefox" to get URL of active tab of front window',
            'Brave Browser': 'tell application "Brave Browser" to get URL of active tab of front window'
        }

        script = browser_scripts.get(app_name)
        if not script:
            return None

        try:
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def capture_activity(self):
        try:
            app_name, window_title = self.get_active_window_mac()

            if not app_name or not window_title:
                return

            # Browser activity
            browsers = ['Google Chrome', 'Safari', 'Firefox', 'Brave Browser', 'Microsoft Edge']
            if app_name in browsers:
                url = self.get_browser_url_mac(app_name) or 'unknown'

                if url != self.last_url or window_title != self.last_title:
                    self.send_event('browser', app_name, {
                        'title': window_title,
                        'url': url,
                        'timestamp': datetime.now().isoformat()
                    })
                    self.last_url = url
                    self.last_title = window_title
                return

            # VS Code activity
            if 'Visual Studio Code' in app_name or 'Code' == app_name:
                # Parse file from title
                title = window_title.replace('●', '').strip()
                if ' — ' in title or ' - ' in title:
                    separator = ' — ' if ' — ' in title else ' - '
                    parts = title.split(separator)
                    filename = parts[0].strip()
                    folder = parts[1].strip() if len(parts) > 1 else 'unknown'

                    if filename != self.last_title:
                        self.send_event('editor', 'VS Code', {
                            'file_path': f"{folder}/{filename}",
                            'file_name': filename,
                            'action': 'focus',
                            'timestamp': datetime.now().isoformat()
                        })
                        self.last_title = filename
                return

            self.last_app = app_name
            self.last_title = window_title

        except Exception as e:
            logger.error(f"Error capturing activity: {e}")

    def run(self):
        logger.info("🕵️ Shadow Agent started (macOS)")
        logger.info(f"📍 Monitoring: {API_BASE_URL}")

        while True:
            try:
                active_session = self.get_active_session()

                if active_session != self.session_id:
                    if active_session:
                        logger.info(f"✅ Active session: {active_session}")
                        self.session_id = active_session
                        self.last_app = None
                        self.last_title = None
                        self.last_url = None
                    else:
                        if self.session_id:
                            logger.info("🛑 Session ended")
                        self.session_id = None

                if self.session_id:
                    self.capture_activity()

                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                logger.info("👋 Agent stopped")
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    agent = ShadowAgentMac()
    agent.run()
AGENT_SCRIPT

# Update API URL in script
sed -i.bak "s|http://10.185.1.180:8000|$API_URL|g" "$INSTALL_DIR/shadow_agent.py"
rm "$INSTALL_DIR/shadow_agent.py.bak" 2>/dev/null || true

# Create requirements.txt
cat > "$INSTALL_DIR/requirements.txt" << 'REQUIREMENTS'
requests>=2.31.0
REQUIREMENTS

echo "✅ Agent script created"

# Install dependencies
echo ""
echo "📦 Installing Python dependencies..."
pip3 install -r "$INSTALL_DIR/requirements.txt" --quiet --user

if [ $? -eq 0 ]; then
    echo "✅ Dependencies installed"
else
    echo "❌ Failed to install dependencies"
    exit 1
fi

# Create LaunchAgent for macOS auto-start
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo ""
    echo "🚀 Setting up auto-start (macOS)..."

    PLIST_FILE="$HOME/Library/LaunchAgents/com.sara.shadowagent.plist"
    mkdir -p "$HOME/Library/LaunchAgents"

    cat > "$PLIST_FILE" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sara.shadowagent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$INSTALL_DIR/shadow_agent.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/.sara/shadow-agent-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.sara/shadow-agent-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>SARA_API_URL</key>
        <string>$API_URL</string>
        <key>SARA_API_TOKEN</key>
        <string>$API_TOKEN</string>
    </dict>
</dict>
</plist>
PLIST

    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    launchctl load "$PLIST_FILE"

    echo "✅ Auto-start configured (LaunchAgent)"
fi

# Create systemd service for Linux
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo ""
    echo "🚀 Setting up auto-start (Linux/systemd)..."

    SERVICE_FILE="$HOME/.config/systemd/user/sara-shadow-agent.service"
    mkdir -p "$HOME/.config/systemd/user"

    cat > "$SERVICE_FILE" << SERVICE
[Unit]
Description=Sara Shadow Mode Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_DIR/shadow_agent.py
Restart=always
Environment="SARA_API_URL=$API_URL"
Environment="SARA_API_TOKEN=$API_TOKEN"

[Install]
WantedBy=default.target
SERVICE

    systemctl --user daemon-reload
    systemctl --user enable sara-shadow-agent.service

    echo "✅ Auto-start configured (systemd)"
fi

# Create uninstaller
cat > "$INSTALL_DIR/uninstall.sh" << 'UNINSTALL'
#!/bin/bash
echo "Uninstalling Sara Shadow Agent..."

if [[ "$OSTYPE" == "darwin"* ]]; then
    launchctl unload "$HOME/Library/LaunchAgents/com.sara.shadowagent.plist" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/com.sara.shadowagent.plist"
fi

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    systemctl --user stop sara-shadow-agent.service 2>/dev/null || true
    systemctl --user disable sara-shadow-agent.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/sara-shadow-agent.service"
    systemctl --user daemon-reload
fi

rm -rf "$HOME/.sara/shadow-agent"
echo "✅ Shadow Agent uninstalled"
UNINSTALL

chmod +x "$INSTALL_DIR/uninstall.sh"

echo ""
echo "🎉 Installation complete!"
echo ""
echo "Configuration:"
echo "  API URL: $API_URL"
echo "  Install Dir: $INSTALL_DIR"
echo "  Log File: $HOME/.sara/shadow-agent.log"
echo ""
echo "The agent will:"
echo "  • Start automatically on login"
echo "  • Monitor browser and VS Code activity"
echo "  • Send events when Shadow session is active"
echo ""

# Start the agent
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "🚀 Agent starting via LaunchAgent..."
    echo "Check logs: tail -f $HOME/.sara/shadow-agent.log"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    read -p "Start the agent now? (Y/n): " START_NOW
    if [[ "$START_NOW" =~ ^[Yy]?$ ]]; then
        systemctl --user start sara-shadow-agent.service
        echo "✅ Agent started"
        echo "Check status: systemctl --user status sara-shadow-agent.service"
    fi
else
    read -p "Start the agent now? (Y/n): " START_NOW
    if [[ "$START_NOW" =~ ^[Yy]?$ ]]; then
        python3 "$INSTALL_DIR/shadow_agent.py" &
        echo "✅ Agent started in background"
    fi
fi

echo ""
echo "To uninstall: bash $INSTALL_DIR/uninstall.sh"
echo ""
