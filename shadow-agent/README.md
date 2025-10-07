# Shadow Mode Desktop Agent for Windows

Automatically captures browser and VS Code activity during Shadow Mode sessions and sends events to Sara.

## Features

✅ **Automatic Activity Capture:**
- Browser activity (Chrome, Firefox, Edge, Brave, Opera)
  - Page titles
  - URL detection
- VS Code activity
  - File paths
  - Folder context
  - File focus events

✅ **Seamless Integration:**
- Auto-starts with Windows
- Only captures during active Shadow sessions
- Runs silently in background
- Logs to `%USERPROFILE%\.sara\shadow-agent.log`

✅ **Privacy-First:**
- No screenshots or keylogging
- Only metadata (titles, URLs, file paths)
- Respects Shadow Mode privacy settings
- Only active when Shadow session is running

## Installation

### Prerequisites
- Windows 10/11
- Administrator access
- Network access to Sara backend (default: `http://10.185.1.180:8000`)

### Quick Install

1. **Download** the installer:
   ```
   Download install.ps1 from the shadow-agent folder
   ```

2. **Run as Administrator**:
   ```powershell
   # Right-click PowerShell -> "Run as Administrator"
   cd Downloads
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

3. **Custom Configuration** (optional):
   ```powershell
   # Specify custom API URL
   powershell -ExecutionPolicy Bypass -File install.ps1 -ApiUrl "http://your-server:8000"

   # With API token (if authentication enabled)
   powershell -ExecutionPolicy Bypass -File install.ps1 -ApiUrl "http://your-server:8000" -ApiToken "your-token"
   ```

### What the Installer Does

1. ✅ Checks for Python (installs 3.11 if missing)
2. ✅ Installs required Python packages:
   - `requests` - HTTP client
   - `psutil` - Process monitoring
   - `PyGetWindow` - Window detection
   - `pywin32` - Windows API access
3. ✅ Copies agent script to `%LOCALAPPDATA%\SaraShadowAgent`
4. ✅ Configures auto-start on Windows login
5. ✅ Starts the agent in background

## Usage

### Starting a Shadow Session

1. **Via Chat** (recommended):
   ```
   "Shadow me for 30 minutes while I work on authentication"
   ```

2. **Via API**:
   ```bash
   curl -X POST http://10.185.1.180:8000/shadow/start \
     -H "Content-Type: application/json" \
     -d '{"duration_minutes": 30, "context": "Working on feature X"}'
   ```

3. **Agent automatically**:
   - Detects active Shadow session (polls every 5 seconds)
   - Starts capturing browser/VS Code activity
   - Sends events to Sara backend
   - Stops when session ends

### Viewing Captured Events

**In Sara Chat:**
```
"Wrap up my shadow session"
```

Sara will show a summary including:
- Tasks and decisions
- Questions and ideas
- Files you worked on (from VS Code)
- Pages you visited (from browser)
- Timeline of activity

**Via API:**
```bash
# Get session status
curl http://10.185.1.180:8000/shadow/{session_id}/status

# Wrap and generate summary
curl -X POST http://10.185.1.180:8000/shadow/{session_id}/wrap
```

## Agent Behavior

### Browser Detection
- **Captured:** Page title, URL (when visible in title)
- **Triggers:** Window focus change, URL change
- **Supported:** Chrome, Firefox, Edge, Brave, Opera

### VS Code Detection
- **Captured:** File path, filename, folder name
- **Triggers:** File focus change
- **Format:** Extracts from window title

### Event Frequency
- Polls for active session: every 5 seconds
- Sends event only when:
  - Window title changes
  - URL changes (browsers)
  - File changes (VS Code)
- **No duplicate events** sent

## Logs and Troubleshooting

### View Logs
```powershell
# PowerShell
Get-Content "$env:USERPROFILE\.sara\shadow-agent.log" -Tail 50 -Wait

# Command Prompt
type %USERPROFILE%\.sara\shadow-agent.log
```

### Common Issues

**Agent not starting:**
```powershell
# Check if Python installed
python --version

# Reinstall dependencies
cd %LOCALAPPDATA%\SaraShadowAgent
python -m pip install -r requirements.txt
```

**Not capturing events:**
- Check Sara backend is running: `http://10.185.1.180:8000`
- Verify Shadow session is active (check Shadow Session Pill in UI)
- Check logs for errors

**Wrong API URL:**
```powershell
# Edit the agent script
notepad %LOCALAPPDATA%\SaraShadowAgent\shadow_agent.py
# Change API_BASE_URL value
# Restart agent
```

## Management Commands

### Stop Agent
```powershell
# Stop running agent
Stop-Process -Name pythonw
```

### Restart Agent
```powershell
# Stop then start
Stop-Process -Name pythonw
Start-Process "%LOCALAPPDATA%\SaraShadowAgent\start_agent.bat" -WindowStyle Hidden
```

### Disable Auto-Start
```powershell
# Remove startup shortcut
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SaraShadowAgent.lnk"
```

### Uninstall
```powershell
# Run uninstaller
powershell -ExecutionPolicy Bypass -File %LOCALAPPDATA%\SaraShadowAgent\uninstall.ps1
```

## Security & Privacy

- **No credentials stored** - Uses session-based authentication
- **Metadata only** - No screenshot or keystroke capture
- **Respects privacy mode** - When enabled, URLs/titles are redacted
- **Local logs** - Stored in user profile, not sent to server
- **Open source** - Code is auditable

## Configuration

### Environment Variables (Optional)
```powershell
# Set custom API URL
[Environment]::SetEnvironmentVariable("SARA_API_URL", "http://your-server:8000", "User")

# Set API token (if auth enabled)
[Environment]::SetEnvironmentVariable("SARA_API_TOKEN", "your-token-here", "User")

# Restart agent for changes to take effect
```

### Edit Agent Settings
```powershell
notepad %LOCALAPPDATA%\SaraShadowAgent\shadow_agent.py
```

**Key settings:**
- `API_BASE_URL` - Sara backend URL
- `API_TOKEN` - Authentication token
- `POLL_INTERVAL` - Seconds between session checks (default: 5)

## Integration with Sara

The agent integrates seamlessly with Sara's Shadow Mode:

1. **Session Detection**: Auto-polls `/shadow/active` endpoint
2. **Event Submission**: Posts to `/shadow/{session_id}/event`
3. **Event Classification**: Backend classifies events automatically
4. **Summary Generation**: Events included in session summary

**Event Metadata Examples:**

Browser event:
```json
{
  "event_type": "browser",
  "app_name": "Chrome",
  "metadata": {
    "title": "FastAPI Documentation",
    "url": "https://fastapi.tiangolo.com",
    "timestamp": "2025-10-04T14:30:00Z"
  }
}
```

Editor event:
```json
{
  "event_type": "editor",
  "app_name": "VS Code",
  "metadata": {
    "file_path": "backend/app/services/shadow_session_service.py",
    "file_name": "shadow_session_service.py",
    "action": "focus",
    "timestamp": "2025-10-04T14:31:00Z"
  }
}
```

## Roadmap

**Future Enhancements:**
- [ ] Terminal command capture
- [ ] Git commit detection
- [ ] Slack/Teams message tracking
- [ ] File save detection (not just focus)
- [ ] Better URL extraction for browsers
- [ ] macOS/Linux support
- [ ] System tray icon with status

## Support

**Logs:** `%USERPROFILE%\.sara\shadow-agent.log`
**Issues:** Check Sara backend logs for API errors
**Reinstall:** Run `uninstall.ps1` then `install.ps1` again

---

🕵️ Happy Shadowing!
