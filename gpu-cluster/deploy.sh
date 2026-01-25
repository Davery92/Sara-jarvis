#!/bin/bash
# GPU Cluster Deployment Script
# Run on: 10.185.1.8

set -e

echo "=== Sara GPU Cluster Deployment ==="
echo ""

# Check we're on the right server
EXPECTED_HOST="10.185.1.8"
CURRENT_IP=$(hostname -I | awk '{print $1}')

if [[ "$CURRENT_IP" != "$EXPECTED_HOST" ]] && [[ "$1" != "--force" ]]; then
    echo "Warning: Expected to run on $EXPECTED_HOST, current IP is $CURRENT_IP"
    echo "Use --force to override"
    exit 1
fi

# Check NVIDIA runtime
echo "Checking NVIDIA Docker runtime..."
if ! docker info 2>/dev/null | grep -q "nvidia"; then
    echo "Installing NVIDIA Docker runtime..."
    distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
    curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
    curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
    sudo apt-get update
    sudo apt-get install -y nvidia-docker2
    sudo systemctl restart docker
fi

# Verify GPUs
echo ""
echo "Checking GPUs..."
nvidia-smi --query-gpu=index,name,memory.total --format=csv
echo ""

# Create directories
echo "Creating data directories..."
sudo mkdir -p /data/riva-models
sudo mkdir -p /data/nemo-models
sudo mkdir -p /data/speakers
sudo mkdir -p /data/audio-uploads
sudo mkdir -p /data/enrollment-samples
sudo chown -R $USER:$USER /data

# Pull images
echo ""
echo "Pulling Docker images..."
docker pull nvcr.io/nvidia/riva/riva-speech:2.14.0 || echo "Riva pull failed - may need NGC login"
docker pull redis:7-alpine
docker pull python:3.11-slim

# Build custom images
echo ""
echo "Building custom images..."
docker compose build nemo-diarization
docker compose build speaker-enrollment
docker compose build audio-worker

# Start services
echo ""
echo "Starting services..."
docker compose up -d audio-redis
sleep 2
docker compose up -d riva-server
docker compose up -d nemo-diarization
docker compose up -d speaker-enrollment
docker compose up -d audio-worker

# Wait for health
echo ""
echo "Waiting for services to be healthy..."
sleep 10

# Check health
echo ""
echo "Service Health:"
echo "  Riva:       $(curl -s http://localhost:8001/v1/health/ready 2>/dev/null | jq -r .status 2>/dev/null || echo 'not ready')"
echo "  NeMo:       $(curl -s http://localhost:8002/health 2>/dev/null | jq -r .status 2>/dev/null || echo 'not ready')"
echo "  Enrollment: $(curl -s http://localhost:8003/health 2>/dev/null | jq -r .status 2>/dev/null || echo 'not ready')"

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "  1. Enroll David: python scripts/enroll_david.py sample1.wav sample2.wav sample3.wav"
echo "  2. Test audio:   curl -X POST http://10.185.1.8:8002/diarize -d '{...}'"
echo ""
