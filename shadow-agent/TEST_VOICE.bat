@echo off
REM Test voice agent with Sara backend
echo.
echo ========================================
echo   Sara Voice Agent - Test Run
echo ========================================
echo.
echo Backend: http://10.185.1.180:8000
echo Wake word: "sarah"
echo.
echo This will test:
echo  1. Wake word detection
echo  2. Speech recognition (VAD)
echo  3. AI response from Sara backend
echo  4. Text-to-speech playback
echo.
echo Press Ctrl+C to stop
echo.
pause

cd /d "%~dp0"

REM Run from dist if available, otherwise from source
if exist "dist\SaraShadowAgent.exe" (
    echo Running from dist\SaraShadowAgent.exe
    echo.
    dist\SaraShadowAgent.exe
) else (
    echo Running from source (src\main_voice.py)
    echo.
    python src\main_voice.py
)

pause
