@echo off
REM Debug script that won't close on error

echo.
echo ================================================
echo WAKE WORD DEBUG
echo ================================================
echo.

cd /d "%~dp0"

echo Running debug checks...
echo.

python scripts\debug_wake_word.py

if errorlevel 1 (
    echo.
    echo ================================================
    echo ERROR DETECTED - See above for details
    echo ================================================
    echo.
)

echo.
echo Press any key to close...
pause >nul
