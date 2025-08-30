#!/bin/bash

# Sara Hub Local Development Setup
echo "🚀 Starting Sara Hub locally..."

# Create local SQLite database instead of PostgreSQL for development
export DATABASE_URL="sqlite:///./sara_hub.db"
export OPENAI_BASE_URL="http://100.104.68.115:11434/v1"
export OPENAI_MODEL="gpt-oss:120b"
export OPENAI_API_KEY="dummy"
export EMBEDDING_BASE_URL="http://100.104.68.115:11434"
export EMBEDDING_MODEL="bge-m3"
export EMBEDDING_DIM="1024"
export ASSISTANT_NAME="Sara"
export DOMAIN="sara.avery.cloud"
export COOKIE_DOMAIN=".sara.avery.cloud"
export CORS_ORIGINS='["https://sara.avery.cloud", "http://localhost:3000"]'
export JWT_SECRET="sara-hub-jwt-secret-development"
export TIMEZONE="America/New_York"

# Skip MinIO for local development
export MINIO_URL="file://./uploads"
export MINIO_BUCKET="sara-docs"
export MINIO_ACCESS_KEY="dummy"
export MINIO_SECRET_KEY="dummy"

echo "📝 Environment configured for local development"

# Install Python dependencies
echo "📦 Installing Python dependencies..."
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "🗄️ Setting up local database..."
# Create a simple database init script for SQLite
python3 -c "
import sqlite3
import logging
logging.basicConfig(level=logging.INFO)

try:
    # Create basic tables for development
    conn = sqlite3.connect('sara_hub.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_user (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    print('✅ Local SQLite database created')
    conn.commit()
    conn.close()
except Exception as e:
    print(f'❌ Database setup failed: {e}')
"

echo "🖥️ Starting backend server..."
# Start backend
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
HOST=${HOST:-0.0.0.0}
DEV_HOST=${DEV_HOST:-localhost}
python3 -m uvicorn app.main:app --host "$HOST" --port 8000 --reload &
BACKEND_PID=$!

cd ../frontend

echo "📦 Installing frontend dependencies..."
npm install

echo "🌐 Starting frontend server..."
npm run dev -- --host "$HOST" --port 3000 &
FRONTEND_PID=$!

echo ""
echo "🎉 Sara Hub is starting up!"
echo ""
echo "📍 Frontend: http://$DEV_HOST:3000"
echo "📍 Backend API: http://$DEV_HOST:8000"
echo ""
echo "Point your nginx proxy manager to: ${DEV_HOST}:3000"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for interrupt
trap "echo 'Stopping services...'; kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait
