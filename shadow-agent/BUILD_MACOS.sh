#!/bin/bash
echo "========================================"
echo "Sara Voice Agent - macOS Builder"
echo "========================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3.9+ from python.org or brew"
    exit 1
fi

echo "[1/4] Installing dependencies..."
pip3 install -r requirements-voice.txt
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies"
    exit 1
fi

echo ""
echo "[2/4] Installing py2app..."
pip3 install py2app
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install py2app"
    exit 1
fi

echo ""
echo "[3/4] Running packaging script..."
python3 package_macos.py
if [ $? -ne 0 ]; then
    echo "ERROR: Packaging failed"
    exit 1
fi

echo ""
echo "[4/4] Done!"
echo ""
echo "========================================"
echo "BUILD COMPLETE!"
echo "========================================"
echo ""
echo "Output location:"
if [ -f "dist/macos/SaraShadowAgent-Installer.dmg" ]; then
    ls -lh dist/macos/SaraShadowAgent-Installer.dmg
    echo ""
    echo "SUCCESS: dist/macos/SaraShadowAgent-Installer.dmg"
else
    echo "ERROR: Installer not found!"
    echo "Note: DMG creation requires macOS. On Linux, the .app bundle is in dist/SaraShadowAgent.app"
fi
echo ""
echo "Next steps:"
echo "1. Test the installer on a clean macOS machine"
echo "2. Upload to server: scp dist/macos/SaraShadowAgent-Installer.dmg server:/path/to/jarvis/shadow-agent/dist/macos/"
echo ""
