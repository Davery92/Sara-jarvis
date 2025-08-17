#!/bin/bash

echo "🚀 Starting Sara Hub (FINAL PRODUCTION)"

# Kill any existing processes
pkill -f "python3 app/main_simple.py" 2>/dev/null
pkill -f "vite.*3000" 2>/dev/null

export PATH="$HOME/.local/bin:$PATH"

cd /home/david/jarvis/backend

echo "📡 Starting Sara backend..."
python3 app/main_simple.py &
BACKEND_PID=$!

cd ../frontend

echo "🌐 Starting Sara frontend..."
npm run dev -- --host 0.0.0.0 --port 3000 &
FRONTEND_PID=$!

sleep 3

echo ""
echo "🎉 Sara Hub is LIVE!"
echo ""
echo "✅ Frontend: https://sara.avery.cloud"
echo "✅ Backend: http://10.185.1.180:8000"
echo "✅ Internal: http://10.185.1.180:3000"
echo ""
echo "🔧 Nginx Proxy Manager Setup:"
echo "   Domain: sara.avery.cloud"
echo "   Forward to: 10.185.1.180:3000"
echo "   SSL: Enabled"
echo ""
echo "🎯 Features Ready:"
echo "   • User authentication (signup/login)"
echo "   • AI chat with Sara"
echo "   • Notes management"
echo "   • CORS configured for sara.avery.cloud"
echo "   • Host headers: ✅ FIXED"
echo ""
echo "🧠 AI Configuration:"
echo "   • LLM: http://100.104.68.115:11434/v1"
echo "   • Model: gpt-oss:120b"
echo "   • Assistant: Sara"
echo ""
echo "Press Ctrl+C to stop"

cleanup() {
    echo ""
    echo "🛑 Stopping Sara Hub..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "👋 Sara is offline"
    exit 0
}

trap cleanup INT
wait