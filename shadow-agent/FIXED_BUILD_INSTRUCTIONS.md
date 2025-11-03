# Sara Voice Agent - Fixed Windows Build Instructions

## Issues Fixed

1. **Unicode/Emoji Encoding Error**:
   - Fixed logging configuration to set UTF-8 encoding BEFORE logging setup
   - Console now properly displays emoji characters in log messages

2. **TFLite Runtime Missing on Windows**:
   - Configured openWakeWord to use ONNX runtime instead of TFLite
   - Added environment variable: `OPENWAKEWORD_INFERENCE_FRAMEWORK=onnx`
   - ONNX runtime is properly available on Windows

3. **PyInstaller Spec Improvements**:
   - Added ONNX runtime hidden imports
   - Included openwakeword resources directory
   - Added UTF-8 encoding support

## Files Modified

### 1. `src/main_voice.py`
- Moved UTF-8 encoding setup BEFORE logging configuration
- Ensures console can display emoji characters

### 2. `src/wake_word.py`
- Added Windows platform detection
- Forces ONNX runtime on Windows via environment variable
- ONNX model (sarah.onnx) properly detected and loaded

### 3. `package_windows.py`
- Enhanced PyInstaller spec with ONNX support
- Added openwakeword resources collection
- Improved hidden imports list

## Building on Windows

### Option 1: Use the Fixed Build Script (Recommended)

1. Copy the updated files to your Windows machine:
   - `src/main_voice.py` (fixed)
   - `src/wake_word.py` (fixed)
   - `BUILD_WINDOWS_FIXED.bat` (new)

2. Run the build script:
   ```cmd
   BUILD_WINDOWS_FIXED.bat
   ```

3. Find your executable in `dist\SaraShadowAgent.exe`

### Option 2: Manual Build

1. Install dependencies:
   ```cmd
   pip install pyinstaller openwakeword onnxruntime sounddevice numpy scipy websockets pystray pillow requests psutil pywin32
   ```

2. Run the updated package script:
   ```cmd
   python package_windows.py
   ```

## Testing the Fixed Build

1. Run the executable:
   ```cmd
   cd dist
   SaraShadowAgent.exe
   ```

2. You should see:
   - ✓ No Unicode encoding errors
   - ✓ "Configured openWakeWord to use ONNX runtime (Windows)"
   - ✓ "Found ONNX model (Windows compatible)"
   - ✓ Agent starts successfully

3. Expected console output:
   ```
   2025-10-10 06:51:05,230 - __main__ - INFO - ============================================================
   2025-10-10 06:51:05,230 - __main__ - INFO - 🎙️  SARA VOICE AGENT
   2025-10-10 06:51:05,231 - __main__ - INFO - ============================================================
   2025-10-10 06:51:05,231 - __main__ - INFO - Backend: ws://10.185.1.180:8000
   2025-10-10 06:51:05,231 - __main__ - INFO - Voice Mode: always_on
   2025-10-10 06:51:05,231 - wake_word - INFO - Configured openWakeWord to use ONNX runtime (Windows)
   2025-10-10 06:51:05,648 - wake_word - INFO - Found ONNX model (Windows compatible)
   2025-10-10 06:51:05,648 - audio_session - INFO - 🚀 Starting voice agent...
   ```

## Configuration

Edit `config.json` in the same directory as the executable:

```json
{
  "backend_url": "ws://10.185.1.180:8000",
  "voice_mode": "always_on",
  "wake_word": {
    "model_path": null,
    "threshold": 0.5,
    "debounce_seconds": 1.5
  },
  "vad": {
    "threshold": 0.5,
    "min_speech_duration_ms": 200,
    "min_silence_duration_ms": 500
  },
  "ui": {
    "show_notifications": true,
    "auto_start": true
  }
}
```

## Troubleshooting

### If you still see encoding errors:
- Ensure you're using the updated `main_voice.py`
- Check Windows console: Right-click title bar → Properties → Font (use TrueType font)

### If ONNX runtime fails:
- Verify `onnxruntime` is installed: `pip show onnxruntime`
- Check that `sarah.onnx` exists in the `models/` directory
- Look for "Configured openWakeWord to use ONNX runtime (Windows)" in logs

### If models aren't found:
- Ensure `models/sarah.onnx` is in the same directory as the .exe
- PyInstaller bundles it, but extracted at runtime to temp directory

## Distribution

The final `SaraShadowAgent.exe` is a standalone executable:
- No Python installation required
- All dependencies bundled
- ~100-150 MB file size
- Can be copied to any Windows machine

## System Requirements

- Windows 10/11 (64-bit)
- Microphone access
- Network access to backend (ws://10.185.1.180:8000)
- ~200 MB disk space (including temp files)
