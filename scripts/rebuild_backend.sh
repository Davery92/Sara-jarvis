#!/bin/bash
# Fast rebuild script for backend Docker container
# Uses layer caching but forces code layer rebuild

set -e

cd /home/david/jarvis

echo "🔍 Checking for requirements.txt changes..."
REQUIREMENTS_HASH=$(md5sum backend/requirements.txt | awk '{print $1}')
CACHE_FILE=".requirements_hash"

# Only rebuild dependencies if requirements.txt changed
if [ -f "$CACHE_FILE" ] && [ "$(cat $CACHE_FILE)" = "$REQUIREMENTS_HASH" ]; then
    echo "✅ Requirements unchanged - using cached layers"
    DOCKER_BUILDKIT=1 docker compose build backend
else
    echo "📦 Requirements changed - rebuilding dependencies"
    DOCKER_BUILDKIT=1 docker compose build --no-cache backend
    echo "$REQUIREMENTS_HASH" > "$CACHE_FILE"
fi

echo "🚀 Restarting backend container..."
docker compose up -d backend

echo "✅ Backend rebuilt and restarted!"
echo "📋 Logs: docker compose logs -f backend"
