@echo off
REM Setup Voice Control on Windows
REM This script installs dependencies and tests your microphone

echo ================================================
echo SARA VOICE CONTROL SETUP (Windows)
echo ================================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.8+ from https://www.python.org/
    pause
    exit /b 1
)

echo [1/5] Python found
python --version
echo.

REM Navigate to shadow-agent directory
cd /d "%~dp0\.."
echo [2/5] Working directory: %CD%
echo.

REM Install voice dependencies
echo [3/5] Installing voice control dependencies...
echo This may take a few minutes...
echo.
pip install -r requirements-voice.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo Done!
echo.

REM Download pre-trained models
echo [4/5] Downloading openWakeWord models...
python -c "import openwakeword; openwakeword.utils.download_models()"
if errorlevel 1 (
    echo ERROR: Failed to download models
    pause
    exit /b 1
)
echo Done!
echo.

REM Test microphone
echo [5/5] Testing your microphone...
echo.
python -c "import sounddevice as sd; print('Available audio devices:'); print(sd.query_devices())"
echo.

echo ================================================
echo SETUP COMPLETE!
echo ================================================
echo.
echo Next steps:
echo   1. Record wake word samples:
echo      python scripts\record_wake_word_windows.py
echo.
echo   2. Test wake word detection (uses 'hey mycroft' for now):
echo      python scripts\test_wake_word.py
echo.
pause
