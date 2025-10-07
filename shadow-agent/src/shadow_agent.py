"""
Shadow Mode Desktop Agent for Windows
Captures browser and VS Code activity and sends to Sara backend
"""
import os
import sys
import time
import json
import logging
import requests
import winreg
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import psutil
import pygetwindow as gw
from urllib.parse import urlparse

# Configuration
API_BASE_URL = os.getenv('SARA_API_URL', 'http://10.185.1.180:8000')
API_TOKEN = os.getenv('SARA_API_TOKEN', '')  # Set via installer
POLL_INTERVAL = 5  # seconds
LOG_FILE = Path.home() / '.sara' / 'shadow-agent.log'

# Setup logging
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


class ShadowAgent:
    def __init__(self):
        self.session_id: Optional[str] = None
        self.last_window = None
        self.last_url = None
        self.last_file = None

    def get_active_session(self) -> Optional[str]:
        """Check for active Shadow session"""
        try:
            headers = {'Authorization': f'Bearer {API_TOKEN}'} if API_TOKEN else {}
            response = requests.get(f'{API_BASE_URL}/shadow/active', headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data.get('id')
            return None
        except Exception as e:
            logger.debug(f"No active session: {e}")
            return None

    def send_event(self, event_type: str, app_name: str, metadata: Dict[str, Any]):
        """Send event to Shadow API"""
        if not self.session_id:
            return

        try:
            headers = {'Authorization': f'Bearer {API_TOKEN}'} if API_TOKEN else {}
            payload = {
                'event_type': event_type,
                'app_name': app_name,
                'metadata': metadata
            }
            response = requests.post(
                f'{API_BASE_URL}/shadow/{self.session_id}/event',
                json=payload,
                headers=headers,
                timeout=5
            )
            if response.status_code == 201:
                logger.info(f"📤 Sent {event_type} event: {app_name}")
            else:
                logger.warning(f"Failed to send event: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending event: {e}")

    def get_browser_info(self, window_title: str, process_name: str) -> Optional[Dict]:
        """Extract URL and title from browser window"""
        # Common browser processes
        browsers = {
            'chrome.exe': 'Chrome',
            'firefox.exe': 'Firefox',
            'msedge.exe': 'Edge',
            'brave.exe': 'Brave',
            'opera.exe': 'Opera'
        }

        if process_name.lower() not in browsers:
            return None

        browser_name = browsers[process_name.lower()]

        # Parse window title for URL hints
        # Format: "Page Title - Browser Name" or "Page Title"
        title = window_title.replace(f' - {browser_name}', '').strip()

        # Try to extract URL from title (some browsers show it)
        url = None
        if ' - ' in title:
            parts = title.split(' - ')
            # Check if last part looks like a URL
            if any(domain in parts[-1].lower() for domain in ['http', 'www', '.com', '.org', '.net']):
                url = parts[-1]
                title = ' - '.join(parts[:-1])

        return {
            'browser': browser_name,
            'title': title,
            'url': url or 'unknown'
        }

    def get_vscode_info(self, window_title: str) -> Optional[Dict]:
        """Extract file path from VS Code window title"""
        # VS Code format: "filename - folder - Visual Studio Code"
        # or "● filename - folder - Visual Studio Code" (unsaved changes)

        title = window_title.replace('Visual Studio Code', '').strip()
        title = title.replace('●', '').strip()  # Remove unsaved indicator

        if ' - ' in title:
            parts = title.split(' - ')
            filename = parts[0].strip()
            folder = parts[1].strip() if len(parts) > 1 else 'unknown'

            return {
                'file_name': filename,
                'folder': folder,
                'file_path': f"{folder}/{filename}" if folder != 'unknown' else filename
            }

        return None

    def capture_activity(self):
        """Capture current window activity"""
        try:
            # Get active window
            active_window = gw.getActiveWindow()
            if not active_window:
                return

            window_title = active_window.title
            if not window_title or window_title == self.last_window:
                return  # No change

            # Get process name
            try:
                for proc in psutil.process_iter(['pid', 'name']):
                    if proc.info['pid'] == active_window._hWnd:
                        process_name = proc.info['name']
                        break
                else:
                    process_name = 'unknown'
            except:
                process_name = 'unknown'

            # Browser activity
            browser_info = self.get_browser_info(window_title, process_name)
            if browser_info:
                # Only send if URL changed
                current_url = browser_info.get('url')
                if current_url != self.last_url:
                    self.send_event('browser', browser_info['browser'], {
                        'title': browser_info['title'],
                        'url': current_url,
                        'timestamp': datetime.now().isoformat()
                    })
                    self.last_url = current_url
                self.last_window = window_title
                return

            # VS Code activity
            if 'visual studio code' in window_title.lower():
                vscode_info = self.get_vscode_info(window_title)
                if vscode_info:
                    current_file = vscode_info.get('file_path')
                    if current_file != self.last_file:
                        self.send_event('editor', 'VS Code', {
                            'file_path': current_file,
                            'file_name': vscode_info.get('file_name'),
                            'action': 'focus',
                            'timestamp': datetime.now().isoformat()
                        })
                        self.last_file = current_file
                self.last_window = window_title
                return

            # Update last window
            self.last_window = window_title

        except Exception as e:
            logger.error(f"Error capturing activity: {e}")

    def run(self):
        """Main agent loop"""
        logger.info("🕵️ Shadow Agent started")
        logger.info(f"📍 Monitoring for active sessions on {API_BASE_URL}")

        while True:
            try:
                # Check for active session
                active_session = self.get_active_session()

                if active_session != self.session_id:
                    if active_session:
                        logger.info(f"✅ Active session detected: {active_session}")
                        self.session_id = active_session
                        # Reset trackers
                        self.last_window = None
                        self.last_url = None
                        self.last_file = None
                    else:
                        if self.session_id:
                            logger.info(f"🛑 Session ended: {self.session_id}")
                        self.session_id = None

                # Capture activity if session active
                if self.session_id:
                    self.capture_activity()

                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                logger.info("👋 Shadow Agent stopped by user")
                break
            except Exception as e:
                logger.error(f"Agent error: {e}")
                time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    agent = ShadowAgent()
    agent.run()
