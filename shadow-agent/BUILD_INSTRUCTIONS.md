# 🔨 Voice Agent Build Instructions

Quick reference for building and testing the Sara Voice Agent packages.

---

## Prerequisites

### Windows Build Environment
```powershell
# Install Python 3.9+ (from python.org)
# Install dependencies
cd shadow-agent
pip install -r requirements-voice.txt
pip install pyinstaller
```

### macOS Build Environment
```bash
# Install Python 3.9+ (from python.org or brew)
# Install dependencies
cd shadow-agent
pip3 install -r requirements-voice.txt
pip3 install py2app
```

---

## Building Packages

### Windows Package
```bash
cd shadow-agent
python package_windows.py
```

**Output:**
- `dist/windows/SaraShadowAgent.exe` - Standalone executable
- `dist/windows/config.json` - Configuration template
- `dist/windows/README.txt` - User instructions
- `dist/SaraShadowAgent-Windows.zip` - **Upload this to backend**

**Build Time:** ~5-10 minutes (first build downloads PyTorch, etc.)

### macOS Package
```bash
cd shadow-agent
python3 package_macos.py
```

**Output:**
- `dist/macos/SaraShadowAgent.app` - Application bundle
- `dist/macos/config.json` - Configuration template
- `dist/macos/README.txt` - User instructions
- `dist/SaraShadowAgent-macOS.zip` - **Upload this to backend**
- `dist/SaraShadowAgent.dmg` - **Upload this too (recommended format)**

**Build Time:** ~5-10 minutes

---

## Testing Locally

### Before Packaging

1. **Test wake word detection:**
```bash
cd shadow-agent
python scripts/test_wake_word.py
```

2. **Test main voice agent:**
```bash
cd shadow-agent
python src/main_voice.py
```

Should see:
```
🎙️  SARA VOICE AGENT
Backend: ws://10.185.1.180:8000
Voice Mode: always_on

✅ Voice agent started
   Mode: always_on
   Say 'sarah' to activate
```

3. **Say "sarah"** - Should trigger detection and start recording

### After Packaging

#### Windows
```powershell
# Extract the ZIP
Expand-Archive dist\SaraShadowAgent-Windows.zip -DestinationPath test_install

# Run the executable
cd test_install
.\SaraShadowAgent.exe
```

#### macOS
```bash
# Extract the ZIP
unzip dist/SaraShadowAgent-macOS.zip -d test_install

# Run the app
open test_install/SaraShadowAgent.app
```

---

## Deployment to Backend

### 1. Copy packages to backend server
```bash
# From your build machine
scp shadow-agent/dist/SaraShadowAgent-Windows.zip user@server:/path/to/jarvis/shadow-agent/dist/
scp shadow-agent/dist/SaraShadowAgent-macOS.zip user@server:/path/to/jarvis/shadow-agent/dist/
scp shadow-agent/dist/SaraShadowAgent.dmg user@server:/path/to/jarvis/shadow-agent/dist/
```

### 2. Verify download endpoints
```bash
# Check download info
curl http://10.185.1.180:8000/api/agent/downloads/info | jq

# Should return:
{
  "version": "1.0.0",
  "platforms": {
    "windows": {
      "platform": "Windows",
      "download_url": "/api/agent/downloads/windows",
      "size_mb": ...
    },
    "macos": {
      "platform": "macOS",
      "formats": [...]
    }
  }
}
```

### 3. Test downloads
```bash
# Download Windows package
curl -o test-windows.zip http://10.185.1.180:8000/api/agent/downloads/windows

# Download macOS package
curl -o test-macos.zip http://10.185.1.180:8000/api/agent/downloads/macos/zip

# Download macOS DMG
curl -o test-macos.dmg http://10.185.1.180:8000/api/agent/downloads/macos/dmg
```

---

## Troubleshooting Build Issues

### Windows

**PyInstaller not found:**
```bash
pip install --upgrade pyinstaller
```

**Missing modules:**
```bash
pip install -r requirements-voice.txt --upgrade
```

**Build fails with "ImportError":**
- Check all imports in source files
- Verify all dependencies are installed
- Try `--clean` flag: `pyinstaller --clean sara_voice.spec`

### macOS

**py2app not found:**
```bash
pip3 install --upgrade py2app
```

**Permission denied:**
```bash
chmod +x setup.py
python3 setup.py py2app
```

**Code signing issues:**
- Build will work without signing for testing
- For distribution, get Apple Developer account and sign:
  ```bash
  codesign --force --sign "Developer ID Application: Your Name" dist/SaraShadowAgent.app
  ```

---

## Configuration for Users

Users can edit `config.json` to customize:

```json
{
  "backend_url": "ws://10.185.1.180:8000",
  "voice_mode": "always_on",  // always_on, shadow_only, push_to_talk
  "wake_word": {
    "threshold": 0.5,  // 0.0-1.0, lower = more sensitive
    "debounce_seconds": 1.5
  },
  "vad": {
    "threshold": 0.5,
    "min_speech_duration_ms": 200,
    "min_silence_duration_ms": 500
  }
}
```

**Common adjustments:**
- Wake word too sensitive: Increase `wake_word.threshold` to 0.6-0.7
- Wake word not detecting: Decrease to 0.3-0.4
- Recording stops too early: Increase `vad.min_silence_duration_ms` to 800-1000
- Too much noise triggers recording: Increase `vad.threshold` to 0.6-0.7

---

## Model Files

Make sure wake word models are present:

```bash
shadow-agent/models/
├── sarah.onnx      # Windows (required)
└── sarah.tflite    # macOS/Linux (required)
```

If missing, users need to:
1. Record wake word: `python scripts/record_wake_word_windows.py`
2. Model will be auto-created in `models/` directory

---

## Logs and Debugging

### Windows
```
%USERPROFILE%\.sara\shadow-agent-voice.log
```

### macOS
```
~/.sara/shadow-agent-voice.log
```

**View logs:**
```bash
# Real-time monitoring
tail -f ~/.sara/shadow-agent-voice.log

# Search for errors
grep ERROR ~/.sara/shadow-agent-voice.log
```

---

## Version Management

Update version in:
1. `backend/app/routes/agent_downloads.py`:
   ```python
   CURRENT_VERSION = "1.0.1"  # Update this
   ```

2. Rebuild packages with new version

3. Backend will automatically serve new version in `/api/agent/downloads/info`

---

## Quick Reference

| Task | Command |
|------|---------|
| Build Windows | `python package_windows.py` |
| Build macOS | `python3 package_macos.py` |
| Test agent locally | `python src/main_voice.py` |
| Check downloads | `curl http://10.185.1.180:8000/api/agent/downloads/info` |
| View logs | `tail -f ~/.sara/shadow-agent-voice.log` |
| Test wake word | `python scripts/test_wake_word.py` |

---

## Support

For issues:
1. Check logs first
2. Verify microphone permissions
3. Test with `test_wake_word.py`
4. Check backend connectivity (can you reach ws://10.185.1.180:8000?)
5. Try adjusting thresholds in config.json

---

**Status:** Ready to build! 🚀
