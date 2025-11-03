@echo off
REM Quick rebuild script for Windows (assumes dependencies already installed)

echo ============================================================
echo SARA VOICE AGENT - QUICK REBUILD
echo ============================================================
echo.

echo [1/3] Installing missing dependencies...
pip install webrtcvad aiohttp

echo.
echo [2/3] Creating PyInstaller spec...
python create_spec.py

echo.
echo [3/3] Building executable (this takes 3-5 minutes)...
python -m PyInstaller --clean --noconfirm sara_voice_fixed.spec

echo.
if exist dist\SaraShadowAgent.exe (
    echo ============================================================
    echo BUILD SUCCESSFUL!
    echo ============================================================
    echo.
    echo Executable: dist\SaraShadowAgent.exe
    dir dist\SaraShadowAgent.exe
    echo.
    echo Test it:
    echo   cd dist
    echo   SaraShadowAgent.exe
    echo.
) else (
    echo ============================================================
    echo BUILD FAILED
    echo ============================================================
    echo.
)

pause
