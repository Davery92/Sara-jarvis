#!/bin/bash

echo "🚀 Starting Sara Hub (Simple Mode)..."

# Set up environment
export PYTHONPATH="$PWD/backend"

# Start backend in simple mode
echo "📡 Starting Sara backend on 10.185.1.180:8000..."
cd backend
python3 -m pip install --user -r requirements-minimal.txt
python3 app/main_simple.py &
BACKEND_PID=$!

cd ../frontend

# Start frontend
echo "🌐 Starting Sara frontend on 10.185.1.180:3000..."
npm install
npm run dev -- --host 10.185.1.180 --port 3000 &
FRONTEND_PID=$!

echo ""
echo "🎉 Sara Hub is running!"
echo ""
echo "📍 Frontend: http://10.185.1.180:3000 ← Point your domain here"
echo "📍 Backend API: http://10.185.1.180:8000"
echo ""
echo "Configure nginx proxy manager:"
echo "  Domain: sara.avery.cloud"
echo "  Forward to: 10.185.1.180:3000"
echo ""
echo "Press Ctrl+C to stop"

# Handle shutdown
cleanup() {
    echo "Stopping Sara Hub..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit 0
}

trap cleanup INT
wait