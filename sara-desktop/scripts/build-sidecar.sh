#!/bin/bash
# Build the Python sidecar executable

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SIDECAR_DIR="$PROJECT_DIR/sidecar"

echo "Building Sara Desktop Sidecar..."
echo "Project directory: $PROJECT_DIR"
echo "Sidecar directory: $SIDECAR_DIR"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 not found"
    exit 1
fi

# Create virtual environment if it doesn't exist
VENV_DIR="$SIDECAR_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Install dependencies from requirements.txt so every platform gets exactly
# what main.py actually imports (voice module deps on all platforms, pyobjc
# only where the "; sys_platform == 'darwin'" marker matches).
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r "$SIDECAR_DIR/requirements.txt"

# Build with PyInstaller
echo "Building executable..."
cd "$SIDECAR_DIR"
pyinstaller --clean sidecar.spec

# Copy to the location electron-builder's extraResources reads from
# (package.json: extraResources.from = "sidecar/dist-frozen").
DIST_DIR="$SIDECAR_DIR/dist-frozen"
mkdir -p "$DIST_DIR"

if [ "$(uname)" == "Darwin" ]; then
    # macOS
    cp "$SIDECAR_DIR/dist/sidecar" "$DIST_DIR/"
elif [ "$(expr substr $(uname -s) 1 5)" == "Linux" ]; then
    # Linux
    cp "$SIDECAR_DIR/dist/sidecar" "$DIST_DIR/"
else
    # Windows (Git Bash)
    cp "$SIDECAR_DIR/dist/sidecar.exe" "$DIST_DIR/"
fi

echo "Sidecar built successfully!"
echo "Output: $DIST_DIR"

# Deactivate virtual environment
deactivate
