@echo off
echo.
echo ================================================
echo TESTING WAKE WORD DETECTION
echo ================================================
echo.

cd /d "%~dp0"

echo Starting wake word test...
echo Say "sarah" when you see "LISTENING FOR WAKE WORD"
echo Press Ctrl+C to stop
echo.
echo ================================================
echo.

python scripts\test_wake_word.py

echo.
echo ================================================
echo Test ended
echo ================================================
echo.
pause
