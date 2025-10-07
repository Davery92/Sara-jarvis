@echo off
REM Quick launcher for recording "sarah" wake word samples
REM Double-click this file to start recording!

cd /d "%~dp0"

echo.
echo ================================================
echo   SARAH WAKE WORD RECORDER
echo ================================================
echo.
echo This will record you saying "sarah" 100 times.
echo Make sure your microphone is connected!
echo.
pause

python scripts\record_wake_word_windows.py

echo.
echo ================================================
echo Recording complete!
echo ================================================
echo.
echo Next step: Generate negative samples
echo Run: GENERATE_NEGATIVES.bat
echo.
pause
