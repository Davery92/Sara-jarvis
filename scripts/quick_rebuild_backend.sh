#!/bin/bash
# Ultra-fast rebuild - only rebuilds code layer (assumes dependencies unchanged)
# Use this for quick code changes

set -e

cd /home/david/jarvis

echo "⚡ Quick rebuild (code only)..."

# Build with cache - only code layer rebuilds due to COPY . .
DOCKER_BUILDKIT=1 docker compose build backend

echo "🚀 Restarting backend container..."
docker compose up -d backend

echo "✅ Backend rebuilt and restarted!"
echo "📋 Logs: docker compose logs -f backend"
