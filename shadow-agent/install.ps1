# Shadow Agent Windows Installer
# Run with: powershell -ExecutionPolicy Bypass -File install.ps1

param(
    [string]$ApiUrl = "http://10.185.1.180:8000",
    [string]$ApiToken = ""
)

Write-Host "Shadow Mode Agent Installer for Windows" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Install directory
$installDir = "$env:LOCALAPPDATA\SaraShadowAgent"
if (-not (Test-Path $installDir)) {
    New-Item -ItemType Directory -Path $installDir | Out-Null
}

Write-Host "Installing Shadow Agent to: $installDir" -ForegroundColor White
Write-Host ""

# Check for Python
Write-Host "Checking for Python..." -ForegroundColor Cyan
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue

if (-not $pythonCmd) {
    Write-Host "Python not found. Installing Python 3.11..." -ForegroundColor Yellow

    $pythonUrl = "https://www.python.org/ftp/python/3.11.8/python-3.11.8-amd64.exe"
    $pythonInstaller = "$env:TEMP\python-installer.exe"

    Write-Host "   Downloading Python..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonInstaller

    Write-Host "   Installing Python (this may take a few minutes)..." -ForegroundColor Gray
    Start-Process -FilePath $pythonInstaller -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1" -Wait

    # Refresh PATH
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path","Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path","User")
    $env:Path = $machinePath + ";" + $userPath

    Remove-Item $pythonInstaller
    Write-Host "Python installed successfully" -ForegroundColor Green
} else {
    $pythonVersion = & python --version
    Write-Host "Python found: $pythonVersion" -ForegroundColor Green
}

# Copy agent files
Write-Host ""
Write-Host "Creating agent script..." -ForegroundColor Cyan

# Download the agent script from GitHub or create it inline
$agentPyPath = "$installDir\shadow_agent.py"
$agentPyUrl = "https://raw.githubusercontent.com/your-repo/shadow-agent/main/shadow_agent_windows.py"

# For now, create inline
$lines = @(
    "import os",
    "import sys",
    "import time",
    "import json",
    "import logging",
    "import requests",
    "from datetime import datetime",
    "from pathlib import Path",
    "from typing import Optional, Dict, Any",
    "",
    "try:",
    "    import win32gui",
    "    import win32process",
    "    import psutil",
    "except ImportError:",
    '    print("Installing required packages...")',
    "    import subprocess",
    '    subprocess.check_call([sys.executable, "-m", "pip", "install", "pywin32", "psutil", "requests"])',
    "    import win32gui",
    "    import win32process",
    "    import psutil",
    "",
    "# Configuration",
    "API_BASE_URL = os.getenv('SARA_API_URL', '$ApiUrl')",
    "API_TOKEN = os.getenv('SARA_API_TOKEN', '')",
    "POLL_INTERVAL = 5",
    "",
    "# Setup logging",
    "LOG_FILE = Path.home() / '.sara' / 'shadow-agent.log'",
    "LOG_FILE.parent.mkdir(exist_ok=True)",
    "logging.basicConfig(",
    "    level=logging.INFO,",
    "    format='%(asctime)s - %(levelname)s - %(message)s',",
    "    handlers=[",
    "        logging.FileHandler(LOG_FILE),",
    "        logging.StreamHandler()",
    "    ]",
    ")",
    "logger = logging.getLogger(__name__)",
    "",
    "",
    "class ShadowAgentWindows:",
    "    def __init__(self):",
    "        self.session_id = None",
    "        self.last_app = None",
    "        self.last_title = None",
    "        self.last_url = None",
    "",
    "    def get_active_session(self):",
    "        try:",
    "            headers = {'Authorization': f'Bearer {API_TOKEN}'} if API_TOKEN else {}",
    "            response = requests.get(f'{API_BASE_URL}/shadow/active', headers=headers, timeout=5)",
    "            if response.status_code == 200:",
    "                data = response.json()",
    "                active = data.get('active_session')",
    "                if active:",
    "                    return active.get('session_id')",
    "            return None",
    "        except Exception as e:",
    "            logger.debug(f'No active session: {e}')",
    "            return None",
    "",
    "    def send_event(self, event_type, app_name, metadata):",
    "        if not self.session_id:",
    "            return",
    "        try:",
    "            headers = {'Authorization': f'Bearer {API_TOKEN}'} if API_TOKEN else {}",
    "            payload = {'event_type': event_type, 'app_name': app_name, 'metadata': metadata}",
    "            response = requests.post(",
    "                f'{API_BASE_URL}/shadow/{self.session_id}/event',",
    "                json=payload, headers=headers, timeout=5",
    "            )",
    "            if response.status_code == 201:",
    "                logger.info(f'Sent {event_type} event: {app_name}')",
    "        except Exception as e:",
    "            logger.error(f'Error sending event: {e}')",
    "",
    "    def get_active_window(self):",
    "        try:",
    "            hwnd = win32gui.GetForegroundWindow()",
    "            if hwnd == 0:",
    "                return None, None",
    "",
    "            title = win32gui.GetWindowText(hwnd)",
    "            _, pid = win32process.GetWindowThreadProcessId(hwnd)",
    "",
    "            try:",
    "                process = psutil.Process(pid)",
    "                app_name = process.name()",
    "                return app_name, title",
    "            except:",
    "                return None, None",
    "        except Exception as e:",
    "            logger.error(f'Error getting active window: {e}')",
    "            return None, None",
    "",
    "    def capture_activity(self):",
    "        try:",
    "            app_name, window_title = self.get_active_window()",
    "",
    "            if not app_name or not window_title:",
    "                return",
    "",
    "            # Browser activity",
    "            browsers = ['chrome.exe', 'firefox.exe', 'msedge.exe', 'brave.exe', 'opera.exe']",
    "            if app_name.lower() in browsers:",
    "                url = window_title.split(' - ')[-1] if ' - ' in window_title else window_title",
    "",
    "                if url != self.last_url or window_title != self.last_title:",
    "                    self.send_event('browser', app_name.replace('.exe', ''), {",
    "                        'title': window_title,",
    "                        'url': url,",
    "                        'timestamp': datetime.now().isoformat()",
    "                    })",
    "                    self.last_url = url",
    "                    self.last_title = window_title",
    "                return",
    "",
    "            # VS Code activity",
    "            if app_name.lower() == 'code.exe':",
    "                title = window_title.replace('●', '').strip()",
    "                if ' - ' in title:",
    "                    parts = title.split(' - ')",
    "                    filename = parts[0].strip()",
    "                    folder = parts[1].strip() if len(parts) > 1 else 'unknown'",
    "",
    "                    if filename != self.last_title:",
    "                        self.send_event('editor', 'VS Code', {",
    "                            'file_path': f'{folder}/{filename}',",
    "                            'file_name': filename,",
    "                            'action': 'focus',",
    "                            'timestamp': datetime.now().isoformat()",
    "                        })",
    "                        self.last_title = filename",
    "                return",
    "",
    "            self.last_app = app_name",
    "            self.last_title = window_title",
    "",
    "        except Exception as e:",
    "            logger.error(f'Error capturing activity: {e}')",
    "",
    "    def run(self):",
    "        logger.info('Shadow Agent started (Windows)')",
    "        logger.info(f'Monitoring: {API_BASE_URL}')",
    "",
    "        while True:",
    "            try:",
    "                active_session = self.get_active_session()",
    "",
    "                if active_session != self.session_id:",
    "                    if active_session:",
    "                        logger.info(f'Active session: {active_session}')",
    "                        self.session_id = active_session",
    "                        self.last_app = None",
    "                        self.last_title = None",
    "                        self.last_url = None",
    "                    else:",
    "                        if self.session_id:",
    "                            logger.info('Session ended')",
    "                        self.session_id = None",
    "",
    "                if self.session_id:",
    "                    self.capture_activity()",
    "",
    "                time.sleep(POLL_INTERVAL)",
    "",
    "            except KeyboardInterrupt:",
    "                logger.info('Agent stopped')",
    "                break",
    "            except Exception as e:",
    "                logger.error(f'Error: {e}')",
    "                time.sleep(POLL_INTERVAL)",
    "",
    "",
    "if __name__ == '__main__':",
    "    agent = ShadowAgentWindows()",
    "    agent.run()"
)

# Replace API URL placeholder
$lines = $lines -replace '\$ApiUrl', $ApiUrl

# Write lines to file
$lines | Out-File -FilePath $agentPyPath -Encoding UTF8

Write-Host "Agent script created" -ForegroundColor Green

# Create requirements.txt
$reqLines = @("requests>=2.31.0", "pywin32>=306", "psutil>=5.9.0")
$reqLines | Out-File -FilePath "$installDir\requirements.txt" -Encoding UTF8

# Install dependencies
Write-Host ""
Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
& python -m pip install --upgrade pip --quiet
& python -m pip install -r "$installDir\requirements.txt" --quiet

if ($LASTEXITCODE -eq 0) {
    Write-Host "Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "Failed to install dependencies" -ForegroundColor Red
    exit 1
}

# Create startup script
Write-Host ""
Write-Host "Setting up auto-start..." -ForegroundColor Cyan

$batPath = "$installDir\start_agent.bat"
$batLines = @("@echo off", "pythonw `"$installDir\shadow_agent.py`"")
$batLines | Out-File -FilePath $batPath -Encoding ASCII

# Add to Windows startup
$WshShell = New-Object -ComObject WScript.Shell
$shortcutPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SaraShadowAgent.lnk"
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $batPath
$shortcut.WorkingDirectory = $installDir
$shortcut.WindowStyle = 7
$shortcut.Description = "Sara Shadow Mode Agent"
$shortcut.Save()

Write-Host "Auto-start configured" -ForegroundColor Green

# Create uninstaller
$uninstallPath = "$installDir\uninstall.ps1"
$uninstallLines = @(
    "Write-Host 'Uninstalling Sara Shadow Agent...' -ForegroundColor Yellow",
    "Stop-Process -Name pythonw -ErrorAction SilentlyContinue",
    "Remove-Item '$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SaraShadowAgent.lnk' -ErrorAction SilentlyContinue",
    "Remove-Item '$installDir' -Recurse -Force",
    "Write-Host 'Shadow Agent uninstalled' -ForegroundColor Green"
)
$uninstallLines | Out-File -FilePath $uninstallPath -Encoding UTF8

# Installation complete
Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Cyan
Write-Host "  API URL: $ApiUrl" -ForegroundColor Gray
Write-Host "  Install Dir: $installDir" -ForegroundColor Gray
Write-Host "  Log File: $env:USERPROFILE\.sara\shadow-agent.log" -ForegroundColor Gray
Write-Host ""
Write-Host "The agent will:" -ForegroundColor White
Write-Host "  - Start automatically on Windows login" -ForegroundColor Gray
Write-Host "  - Monitor browser and VS Code activity" -ForegroundColor Gray
Write-Host "  - Send events when Shadow session is active" -ForegroundColor Gray
Write-Host ""

$startNow = Read-Host "Start the agent now? (Y/n)"
if ($startNow -eq "" -or $startNow -eq "Y" -or $startNow -eq "y") {
    Write-Host ""
    Write-Host "Starting Shadow Agent..." -ForegroundColor Cyan
    Start-Process -FilePath $batPath -WindowStyle Hidden
    Write-Host "Agent started in background" -ForegroundColor Green
    Write-Host ""
    Write-Host "Check logs at: $env:USERPROFILE\.sara\shadow-agent.log" -ForegroundColor Gray
}

Write-Host ""
Write-Host "To uninstall: powershell -ExecutionPolicy Bypass -File `"$installDir\uninstall.ps1`"" -ForegroundColor Gray
Write-Host ""
