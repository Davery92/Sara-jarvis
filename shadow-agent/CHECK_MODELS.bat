@echo off
echo Checking if models are bundled in executable...
echo.

cd dist
if exist models (
    echo [OK] models folder exists
    dir models
) else (
    echo [ERROR] models folder missing!
    echo.
    echo The PyInstaller build didn't include the models directory.
    echo You need to manually copy it:
    echo.
    echo   copy ..\models dist\models /E
    echo.
)

pause
