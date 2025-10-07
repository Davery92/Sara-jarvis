@echo off
cls
echo.
echo ================================================
echo   SARA VOICE CONTROL - QUICK START
echo ================================================
echo.
echo Welcome! This wizard will help you set up voice
echo control for Sara with a custom "sarah" wake word.
echo.
echo ================================================
echo.
echo What would you like to do?
echo.
echo [1] Setup voice control (first time)
echo [2] Record "sarah" wake word samples
echo [3] Generate negative samples
echo [4] Test wake word detection
echo [5] View full setup guide
echo [0] Exit
echo.
set /p choice="Enter your choice (0-5): "

if "%choice%"=="1" goto setup
if "%choice%"=="2" goto record
if "%choice%"=="3" goto negatives
if "%choice%"=="4" goto test
if "%choice%"=="5" goto guide
if "%choice%"=="0" goto end

echo Invalid choice. Please try again.
pause
goto menu

:menu
goto menu

:setup
cls
echo.
echo ================================================
echo   SETUP VOICE CONTROL
echo ================================================
echo.
call scripts\setup_voice_windows.bat
echo.
echo Setup complete! Press any key to return to menu...
pause >nul
goto menu

:record
cls
echo.
echo ================================================
echo   RECORD WAKE WORD
echo ================================================
echo.
python scripts\record_wake_word_windows.py
echo.
pause
goto end

:negatives
cls
echo.
echo ================================================
echo   GENERATE NEGATIVE SAMPLES
echo ================================================
echo.
python scripts\generate_negative_samples.py
echo.
pause
goto end

:test
cls
echo.
echo ================================================
echo   TEST WAKE WORD DETECTION
echo ================================================
echo.
python scripts\test_wake_word.py
goto end

:guide
cls
type VOICE_SETUP_GUIDE.md
echo.
echo Press any key to return to menu...
pause >nul
goto menu

:end
echo.
echo Goodbye!
echo.
