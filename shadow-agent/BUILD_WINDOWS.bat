@echo off
echo ========================================
echo Sara Voice Agent - Windows Builder
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.9+ from python.org
    pause
    exit /b 1
)

echo [1/4] Installing dependencies...
pip install -r requirements-voice.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo [2/4] Installing PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install PyInstaller
    pause
    exit /b 1
)

echo.
echo [3/4] Running packaging script...
python package_windows.py
if errorlevel 1 (
    echo ERROR: Packaging failed
    pause
    exit /b 1
)

echo.
echo [4/4] Done!
echo.
echo ========================================
echo BUILD COMPLETE!
echo ========================================
echo.
echo Output location:
dir dist\windows\SaraShadowAgent-Installer.exe 2>nul
if errorlevel 1 (
    echo ERROR: Installer not found!
) else (
    echo SUCCESS: dist\windows\SaraShadowAgent-Installer.exe
)
echo.
echo Next steps:
echo 1. Test the installer on a clean Windows machine
echo 2. Upload to server: scp dist\windows\SaraShadowAgent-Installer.exe server:/path/to/jarvis/shadow-agent/dist/windows/
echo.
pause
