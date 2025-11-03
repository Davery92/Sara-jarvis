@echo off
REM Run Sara Voice Agent with precise timestamps for performance testing
echo.
echo ========================================
echo   Sara Voice Agent - Performance Test
echo ========================================
echo.
echo This will show precise timestamps to measure:
echo  - Wake word detection latency
echo  - STT processing time (should be 3-5s now!)
echo  - AI response time
echo  - TTS generation time
echo.
echo Target: Recording stop to transcript in 3-5 seconds
echo Previous: 13-16 seconds
echo.
pause

cd /d "%~dp0"

REM Set Python to show timestamps in logs
set PYTHONUNBUFFERED=1

if exist "dist\SaraShadowAgent.exe" (
    echo Running: dist\SaraShadowAgent.exe
    echo.
    dist\SaraShadowAgent.exe
) else (
    echo Running from source with timestamps
    echo.
    python src\main_voice.py
)

pause
