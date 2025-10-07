@echo off
REM Quick launcher for generating negative training samples
REM Run this after recording your "sarah" samples

cd /d "%~dp0"

echo.
echo ================================================
echo   NEGATIVE SAMPLE GENERATOR
echo ================================================
echo.
echo This will generate synthetic negative samples
echo using Sara's TTS service.
echo.
echo Make sure TTS is running at: http://10.185.1.8:9000
echo.
pause

python scripts\generate_negative_samples.py

echo.
echo ================================================
echo Generation complete!
echo ================================================
echo.
echo Next steps:
echo 1. Review training data in training_data/ folder
echo 2. Follow VOICE_SETUP_GUIDE.md for training instructions
echo.
pause
