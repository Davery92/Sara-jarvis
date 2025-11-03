@echo off
REM Quick rebuild with optimizations
echo.
echo ========================================
echo   Sara Voice Agent - Optimized Rebuild
echo ========================================
echo.
echo Optimizations:
echo  - Conversational history (per computer)
echo  - Fast STT path (3-5x faster transcription)
echo  - Direct HTTP to STT service
echo.
echo This will:
echo  1. Create PyInstaller spec
echo  2. Build single executable
echo  3. Bundle wake word model
echo.
pause

cd /d "%~dp0"

echo.
echo [1/3] Creating PyInstaller spec...
python create_spec.py
if errorlevel 1 (
    echo ERROR: Failed to create spec file
    pause
    exit /b 1
)

echo.
echo [2/3] Building executable (this may take 5-10 minutes)...
python -m PyInstaller --clean --noconfirm sara_voice_fixed.spec
if errorlevel 1 (
    echo ERROR: Build failed
    pause
    exit /b 1
)

echo.
echo [3/3] Verifying build...
if exist "dist\SaraShadowAgent.exe" (
    echo ✅ Build successful: dist\SaraShadowAgent.exe
    echo.
    echo File size:
    dir dist\SaraShadowAgent.exe | find "SaraShadowAgent.exe"
    echo.
    echo To run: dist\SaraShadowAgent.exe
    echo Or use: TEST_VOICE.bat
) else (
    echo ❌ Build failed - executable not found
    echo.
    echo Checking dist folder contents:
    dir dist\*.exe
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Build Complete!
echo ========================================
echo.
pause
