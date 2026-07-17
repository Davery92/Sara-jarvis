#!/bin/bash
# Sara Voice + Vision Agent — One-shot installation for Jetson Orin Nano
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"

echo "========================================="
echo "Sara Voice + Vision Agent — Installation"
echo "========================================="
echo "Project: $PROJECT_DIR"
echo ""

# Check we're on a Jetson (or skip for development)
if [ -f /etc/nv_tegra_release ]; then
    echo "Detected Jetson platform:"
    cat /etc/nv_tegra_release
else
    echo "WARNING: Not running on Jetson. Some features may not work."
fi
echo ""

# Create virtual environment
echo ">>> Creating virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Upgrade pip
echo ">>> Upgrading pip..."
pip install --upgrade pip wheel setuptools

# Install dependencies
echo ">>> Installing Python dependencies..."
pip install -r "$PROJECT_DIR/requirements.txt"

# Create directories
echo ">>> Creating directories..."
mkdir -p "$PROJECT_DIR/models"
mkdir -p "$PROJECT_DIR/logs"

# Download Silero VAD model
echo ">>> Downloading Silero VAD model..."
SILERO_URL="https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
if [ ! -f "$PROJECT_DIR/models/silero_vad.onnx" ]; then
    wget -q -O "$PROJECT_DIR/models/silero_vad.onnx" "$SILERO_URL"
    echo "   Downloaded silero_vad.onnx"
else
    echo "   silero_vad.onnx already exists"
fi

# Check for wake word model
if [ ! -f "$PROJECT_DIR/models/hey_sara.onnx" ]; then
    echo ""
    echo "NOTE: Wake word model 'hey_sara.onnx' not found."
    echo "      You'll need to train one using OpenWakeWord."
    echo "      Place it at: $PROJECT_DIR/models/hey_sara.onnx"
    echo "      The system will use built-in models as fallback."
fi

# Check for whisper model
if [ ! -f "$PROJECT_DIR/models/ggml-base.en.bin" ]; then
    echo ""
    echo "NOTE: Local Whisper model not found."
    echo "      For local STT fallback, download:"
    echo "      wget -O $PROJECT_DIR/models/ggml-base.en.bin \\"
    echo "        https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
fi

# Check for face embedding
if [ ! -f "$PROJECT_DIR/models/david_face.npy" ]; then
    echo ""
    echo "NOTE: David face embedding not found."
    echo "      Vision-based face recognition will be disabled."
    echo "      Run face enrollment to create: $PROJECT_DIR/models/david_face.npy"
fi

echo ""
echo "========================================="
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Set environment variables:"
echo "     export SARA_USERNAME='your_username'"
echo "     export SARA_PASSWORD='your_password'"
echo ""
echo "  2. Test audio:"
echo "     make test"
echo ""
echo "  3. Run the service:"
echo "     make start"
echo ""
echo "  4. Install as systemd service:"
echo "     make service-install"
echo "     sudo systemctl start sara-voice"
echo "========================================="
