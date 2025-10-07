@echo off
REM Simple standalone setup script
REM Run this first to install dependencies

echo.
echo ================================================
echo SARA VOICE CONTROL SETUP
echo ================================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.8+ from https://www.python.org/
    echo.
    pause
    exit /b 1
)

echo [1/4] Python found
python --version
echo.

REM Install dependencies
echo [2/4] Installing voice dependencies...
echo This may take a few minutes...
echo.
pip install -r requirements-voice.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies
    echo.
    pause
    exit /b 1
)
echo.
echo Done!
echo.

REM Download models
echo [3/4] Downloading openWakeWord models...
python -c "import openwakeword; openwakeword.utils.download_models()"
if errorlevel 1 (
    echo.
    echo ERROR: Failed to download models
    echo.
    pause
    exit /b 1
)
echo.
echo Done!
echo.

REM Test microphone
echo [4/4] Testing microphone...
echo.
python -c "import sounddevice as sd; print('Available audio devices:'); print(sd.query_devices())"
echo.

echo.
echo ================================================
echo SETUP COMPLETE!
echo ================================================
echo.
echo Next steps:
echo   1. Record wake word: RECORD_SARAH.bat
echo   2. Generate negatives: GENERATE_NEGATIVES.bat
echo   3. Train model (see QUICKSTART.md)
echo   4. Test detection: python scripts\test_wake_word.py
echo.
echo For full menu, run: START_HERE.bat
echo.
pause
