@echo off
REM Sara Desktop Sidecar Setup for Windows
REM Creates a virtual environment and installs dependencies.

echo Sara Desktop Sidecar Setup
echo ==========================

set SCRIPT_DIR=%~dp0
set VENV_DIR=%SCRIPT_DIR%venv

REM Check for Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python not found.
    echo Please install Python 3 from https://python.org
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do echo Using %%i

REM Create virtual environment if it doesn't exist
if not exist "%VENV_DIR%" (
    echo.
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    echo Virtual environment created at %VENV_DIR%
)

REM Upgrade pip
echo.
echo Upgrading pip...
"%VENV_DIR%\Scripts\pip.exe" install --upgrade pip >nul

REM Install dependencies
echo.
echo Installing dependencies...
"%VENV_DIR%\Scripts\pip.exe" install -r "%SCRIPT_DIR%requirements.txt"

echo.
echo Setup complete!
echo.
echo The sidecar will automatically use this virtual environment.
echo You can now start the Sara desktop app.
pause
