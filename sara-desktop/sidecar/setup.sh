#!/bin/bash
#
# Sara Desktop Sidecar Setup
#
# Creates a virtual environment and installs dependencies.
# Run this once before starting the desktop app.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

echo "Sara Desktop Sidecar Setup"
echo "=========================="

# Detect Python
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "Error: Python 3 not found."
    echo ""
    echo "Please install Python 3:"
    echo "  macOS: brew install python3"
    echo "  Windows: Download from https://python.org"
    exit 1
fi

echo "Using Python: $($PYTHON --version)"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
    echo "Virtual environment created at $VENV_DIR"
fi

# Determine pip path
if [ -f "$VENV_DIR/bin/pip" ]; then
    PIP="$VENV_DIR/bin/pip"
elif [ -f "$VENV_DIR/Scripts/pip.exe" ]; then
    PIP="$VENV_DIR/Scripts/pip.exe"
else
    echo "Error: pip not found in virtual environment"
    exit 1
fi

# Upgrade pip
echo ""
echo "Upgrading pip..."
$PIP install --upgrade pip > /dev/null

# Install dependencies
echo ""
echo "Installing dependencies..."
$PIP install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "Setup complete!"
echo ""
echo "The sidecar will automatically use this virtual environment."
echo "You can now start the Sara desktop app."
