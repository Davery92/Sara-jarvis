#!/bin/bash

echo "🚀 Starting Sara Hub Demo..."

# Start simple backend
echo "📡 Starting demo backend..."
python3 simple-demo.py &
BACKEND_PID=$!

# Start frontend
echo "🌐 Starting frontend..."
cd frontend

# Quick install and start
npm install > /dev/null 2>&1 &
INSTALL_PID=$!

echo "📦 Installing frontend dependencies in background..."
echo "⏳ This may take a moment..."

# Wait for npm install to complete
wait $INSTALL_PID

echo "🎯 Starting Sara frontend on 10.185.1.180:3000..."
npm run dev -- --host 10.185.1.180 --port 3000 &
FRONTEND_PID=$!

echo ""
echo "🎉 Sara Hub Demo is running!"
echo ""
echo "📍 Frontend: http://10.185.1.180:3000 ← Point sara.avery.cloud here"
echo "📍 Backend Demo: http://10.185.1.180:8000"
echo ""
echo "🔧 Configure nginx proxy manager:"
echo "   Domain: sara.avery.cloud"
echo "   Forward to: 10.185.1.180:3000"
echo "   Enable SSL"
echo ""
echo "ℹ️  Note: Backend is running in demo mode"
echo "   For full functionality, install:"
echo "   - FastAPI, SQLAlchemy, pgvector"
echo "   - PostgreSQL database"
echo "   - Complete backend dependencies"
echo ""
echo "Press Ctrl+C to stop all services"

# Handle cleanup
cleanup() {
    echo ""
    echo "🛑 Stopping Sara Hub Demo..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "👋 Goodbye!"
    exit 0
}

trap cleanup INT

# Wait for interrupt
wait