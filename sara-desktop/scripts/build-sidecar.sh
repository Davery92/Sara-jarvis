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

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip

# Install openwakeword without deps first (tflite-runtime not available for Python 3.12)
pip install --no-deps openwakeword

# Install other dependencies (tensorflow-cpu replaces tflite-runtime)
pip install onnxruntime tqdm scipy scikit-learn numpy requests tensorflow-cpu \
    pyaudio pynput mss Pillow websockets httpx pyinstaller

# Build with PyInstaller
echo "Building executable..."
cd "$SIDECAR_DIR"
pyinstaller --clean sidecar.spec

# Copy to release location
DIST_DIR="$PROJECT_DIR/release/sidecar"
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
