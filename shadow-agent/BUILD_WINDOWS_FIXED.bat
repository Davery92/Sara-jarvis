@echo off
REM Windows Build Script with Fixes for ONNX and Unicode
REM Run this on your Windows machine to rebuild with fixes

echo ============================================================
echo SARA VOICE AGENT - WINDOWS BUILD (FIXED)
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

echo [1/5] Installing dependencies...
pip install pyinstaller openwakeword onnxruntime sounddevice numpy scipy websockets pystray pillow requests psutil pywin32 webrtcvad aiohttp

if errorlevel 1 (
    echo [WARNING] Some packages may have failed to install
    echo Continuing anyway...
)

echo.
echo [2/5] Creating PyInstaller spec file...
python create_spec.py

if errorlevel 1 (
    echo [ERROR] Failed to create spec file
    pause
    exit /b 1
)

echo.
echo [3/5] Creating config template...
python -c "import json; json.dump({'backend_url': 'ws://10.185.1.180:8000', 'voice_mode': 'always_on', 'wake_word': {'model_path': None, 'threshold': 0.5, 'debounce_seconds': 1.5}, 'vad': {'threshold': 0.5, 'min_speech_duration_ms': 200, 'min_silence_duration_ms': 500}, 'ui': {'show_notifications': True, 'auto_start': True}}, open('config.json.example', 'w'), indent=2)"

echo.
echo [4/5] Building executable...
echo This may take several minutes...
echo.
python -m PyInstaller --clean --noconfirm sara_voice_fixed.spec

if errorlevel 1 (
    echo.
    echo ============================================================
    echo [ERROR] BUILD FAILED
    echo ============================================================
    echo Check the output above for errors
    pause
    exit /b 1
)

echo.
echo [5/5] Checking output...
if exist dist\SaraShadowAgent.exe (
    echo.
    echo ============================================================
    echo BUILD SUCCESSFUL!
    echo ============================================================
    echo.
    echo Executable: dist\SaraShadowAgent.exe
    dir dist\SaraShadowAgent.exe
    echo.
    echo Next steps:
    echo   1. Test: cd dist ^&^& SaraShadowAgent.exe
    echo   2. Copy models folder to dist\ if not auto-included
    echo   3. Distribute dist\SaraShadowAgent.exe
    echo.
) else (
    echo.
    echo ============================================================
    echo BUILD FAILED - Executable not found
    echo ============================================================
    echo Check the PyInstaller output above for errors
    echo.
)

pause
