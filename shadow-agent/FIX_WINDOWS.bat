@echo off
echo.
echo ================================================
echo FIXING WINDOWS TFLITE ISSUE
echo ================================================
echo.
echo Installing onnxruntime for Windows...
echo (tflite-runtime doesn't work on Windows)
echo.

pip install onnxruntime

echo.
echo ================================================
echo Done!
echo ================================================
echo.
echo Your sarah.tflite model needs to be converted to ONNX format.
echo.
echo Two options:
echo.
echo Option 1 (Recommended): Re-train your model in Colab
echo   - When training, save as ONNX instead of TFLite
echo   - Or export both formats
echo.
echo Option 2: Convert existing model
echo   - Run: python scripts\convert_tflite_to_onnx.py
echo.
pause
