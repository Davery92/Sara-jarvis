#!/bin/bash

echo "🚀 Starting Sara Hub (Production Mode)..."

# Set up environment and PATH
export PATH="$HOME/.local/bin:$PATH"
export PYTHONPATH="/home/david/jarvis/backend"

# Production environment variables
# Respect existing DATABASE_URL; do not override if set. Avoid SQLite in production by default.
if [ -z "$DATABASE_URL" ]; then
  # Uncomment and set your production database URI (PostgreSQL recommended)
  # export DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.188:5432/sara_hub"
  echo "WARN: DATABASE_URL is not set. The backend will use its configured default."
fi
export OPENAI_BASE_URL="http://100.104.68.115:11434/v1"
export OPENAI_MODEL="gpt-oss:120b"
export OPENAI_API_KEY="dummy"
export EMBEDDING_BASE_URL="http://100.104.68.115:11434"
export EMBEDDING_MODEL="bge-m3"
export EMBEDDING_DIM="1024"
export ASSISTANT_NAME="Sara"
export DOMAIN="sara.avery.cloud"
export FRONTEND_URL="https://sara.avery.cloud"
export BACKEND_URL="https://sara.avery.cloud/api"
export COOKIE_DOMAIN=".sara.avery.cloud"
export CORS_ORIGINS='["https://sara.avery.cloud", "http://sara.avery.cloud", "http://localhost:3000", "http://10.185.1.180:3000", "http://10.185.1.188:3000"]'
export JWT_SECRET="sara-hub-jwt-secret-production"
export COOKIE_SECURE="false"
export TIMEZONE="America/New_York"

# Web search (SearXNG) and caching
export SEARXNG_BASE_URL="${SEARXNG_BASE_URL:-http://10.185.1.8:4000}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

# MinIO/Storage (local file system for now)
export MINIO_URL="file://./uploads"
export MINIO_BUCKET="sara-docs"
export MINIO_ACCESS_KEY="dummy"
export MINIO_SECRET_KEY="dummy"

# Memory settings
export MEMORY_CHUNK_SIZE="700"
export MEMORY_CHUNK_OVERLAP="150"
export MEMORY_SEARCH_LIMIT="12"

cd /home/david/jarvis

echo "📡 Starting Sara backend (Full FastAPI)..."
cd backend

# Create uploads directory
mkdir -p uploads

# Start the full FastAPI backend
python3 app/main_simple.py &
BACKEND_PID=$!

cd ../frontend

echo "🌐 Starting Sara frontend..."
npm run dev -- --host 0.0.0.0 --port 3000 &
FRONTEND_PID=$!

echo ""
echo "🎉 Sara Hub Production is running!"
echo ""
echo "📍 Frontend: https://sara.avery.cloud ← Your domain"
echo "📍 Backend API: http://10.185.1.188:8000 (prod) / http://10.185.1.180:8000 (dev)"
echo "📍 Internal: http://10.185.1.188:3000 (prod) / http://10.185.1.180:3000 (dev)"
echo ""
echo "🔧 Nginx Proxy Manager:"
echo "   Domain: sara.avery.cloud"
echo "   Forward to: 10.185.1.180:3000"
echo "   SSL: Enabled"
echo ""
echo "✅ Features Available:"
echo "   • Authentication with JWT cookies"
echo "   • Basic chat functionality" 
echo "   • Notes management"
echo "   • SQLite database"
echo "   • CORS configured for sara.avery.cloud"
echo ""
echo "🔧 For Advanced AI Features:"
echo "   • Install: postgresql, pgvector"
echo "   • Install: sentence-transformers, pypdf"
echo "   • Switch DATABASE_URL to PostgreSQL"
echo ""
echo "Press Ctrl+C to stop all services"

# Handle cleanup
cleanup() {
    echo ""
    echo "🛑 Stopping Sara Hub..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "👋 Sara is offline"
    exit 0
}

trap cleanup INT

# Wait for interrupt
wait
