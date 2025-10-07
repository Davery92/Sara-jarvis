@echo off
echo.
echo Testing Python and packages...
echo.

REM Test Python
echo [1] Python version:
python --version
echo.

REM Test openwakeword
echo [2] Testing openwakeword import:
python -c "import openwakeword; print('   OK - openwakeword installed')"
if errorlevel 1 (
    echo    ERROR - openwakeword not installed
    echo    Run: pip install openwakeword
)
echo.

REM Test sounddevice
echo [3] Testing sounddevice import:
python -c "import sounddevice; print('   OK - sounddevice installed')"
if errorlevel 1 (
    echo    ERROR - sounddevice not installed
    echo    Run: pip install sounddevice
)
echo.

REM Test numpy
echo [4] Testing numpy import:
python -c "import numpy; print('   OK - numpy installed')"
if errorlevel 1 (
    echo    ERROR - numpy not installed
    echo    Run: pip install numpy
)
echo.

REM Check model file
echo [5] Checking for sarah.tflite:
if exist models\sarah.tflite (
    echo    OK - Model found at models\sarah.tflite
) else (
    echo    ERROR - Model not found at models\sarah.tflite
    echo    Please copy your sarah.tflite file to the models folder
)
echo.

echo ================================================
echo If all tests show OK, try running:
echo    python scripts\test_wake_word.py
echo ================================================
echo.
pause
