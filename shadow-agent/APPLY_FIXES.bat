@echo off
REM Apply latest fixes and rebuild
echo.
echo ========================================
echo   Sara Voice Agent - v2.3
echo   Conversation Mode Update
echo ========================================
echo.
echo NEW FEATURES:
echo  ✨ CONVERSATION MODE - Natural multi-turn dialog
echo     Say "Sarah" once, then keep talking!
echo     No wake word needed for follow-up messages
echo     Automatic 5-second timeout
echo.
echo FIXES:
echo  ✅ Immediate recording after wake word (no first word loss)
echo  ✅ TTS echo prevention (2-second suppression window)
echo  ✅ Better state management after TTS playback
echo  ✅ Enhanced logging for debugging
echo.
echo This will rebuild the executable with conversation mode.
echo.
pause

cd /d "%~dp0"

echo.
echo [1/4] Cleaning old build...
if exist "build" (
    rmdir /s /q build
    echo ✓ Removed build folder
)
if exist "dist\SaraShadowAgent.exe" (
    del /f /q "dist\SaraShadowAgent.exe"
    echo ✓ Removed old executable
)

echo.
echo [2/4] Creating PyInstaller spec...
python create_spec.py
if errorlevel 1 (
    echo ERROR: Failed to create spec file
    pause
    exit /b 1
)

echo.
echo [3/4] Building with fixes (this may take 5-10 minutes)...
python -m PyInstaller --clean --noconfirm sara_voice_fixed.spec
if errorlevel 1 (
    echo ERROR: Build failed
    pause
    exit /b 1
)

echo.
echo [4/4] Verifying build...
if exist "dist\SaraShadowAgent.exe" (
    echo.
    echo ✅ BUILD SUCCESSFUL!
    echo.
    echo Executable: dist\SaraShadowAgent.exe
    echo.
    echo File size:
    dir dist\SaraShadowAgent.exe | find "SaraShadowAgent.exe"
    echo.
    echo ========================================
    echo   What's Fixed:
    echo ========================================
    echo.
    echo 1. IMMEDIATE RECORDING after wake word
    echo    - No more missing first words
    echo    - Recording starts instantly after "sarah"
    echo.
    echo 2. CONVERSATION MODE (NEW!)
    echo    - Say "Sarah" ONCE to start conversation
    echo    - Keep talking without repeating wake word
    echo    - After Sara responds, just start talking
    echo    - 5-second timeout returns to wake word mode
    echo    - Natural back-and-forth dialog
    echo.
    echo 3. TTS ECHO PREVENTION
    echo    - 2-second suppression after TTS playback
    echo    - No false wake word from Sara's voice
    echo    - Consistent behavior every round
    echo.
    echo 4. BETTER LOGGING
    echo    - Clear state transitions
    echo    - Easier to debug issues
    echo    - Shows "Ready for next wake word" message
    echo.
    echo ========================================
    echo   To Test:
    echo ========================================
    echo.
    echo Run: TEST_VOICE.bat
    echo.
    echo Test sequence (Conversation Mode):
    echo  1. Say: "Sarah"
    echo  2. Then say: "Get ready, we have lots of work to do"
    echo  3. Wait for Sara's response
    echo  4. Just start talking (NO "Sarah" needed!)
    echo     Say: "Let's start with the project timeline"
    echo  5. Wait for response
    echo  6. Keep talking (NO "Sarah" needed!)
    echo     Say: "What about the budget?"
    echo  7. Continue conversation naturally
    echo  8. Stop talking for 5 seconds → exits conversation mode
    echo.
    echo Old way (still works):
    echo  - Say "Sarah" before every message
    echo  - Conversation mode will activate anyway
    echo.
) else (
    echo.
    echo ❌ BUILD FAILED - executable not found
    echo.
    echo Checking dist folder:
    if exist "dist" (
        dir dist\*.exe
    ) else (
        echo Dist folder does not exist
    )
    pause
    exit /b 1
)

echo.
pause
