#!/usr/bin/env python3

import http.server
import socketserver
import json
import urllib.parse
from datetime import datetime
import os

PORT = 8000
HOST = "10.185.1.180"

class SaraHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            response = {
                "message": "Welcome to Sara Personal Hub API",
                "version": "1.0.0-demo", 
                "assistant": "Sara",
                "domain": "sara.avery.cloud",
                "time": datetime.now().isoformat()
            }
            self.wfile.write(json.dumps(response, indent=2).encode())
            
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            response = {
                "status": "healthy",
                "assistant": "Sara",
                "uptime": "demo mode"
            }
            self.wfile.write(json.dumps(response, indent=2).encode())
            
        elif self.path.startswith("/api"):
            # Redirect API calls
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            response = {
                "message": "Sara API endpoint",
                "endpoint": self.path,
                "note": "This is a demo - full API requires proper dependencies"
            }
            self.wfile.write(json.dumps(response, indent=2).encode())
            
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"error": "Not found"}')
    
    def do_POST(self):
        # Handle POST requests
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        
        response = {
            "message": "Sara received your request",
            "endpoint": self.path,
            "method": "POST",
            "note": "This is a demo server - full functionality requires proper setup"
        }
        self.wfile.write(json.dumps(response, indent=2).encode())
    
    def do_OPTIONS(self):
        # Handle CORS preflight
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

if __name__ == "__main__":
    with socketserver.TCPServer((HOST, PORT), SaraHandler) as httpd:
        print(f"🚀 Sara Hub Demo Server")
        print(f"📡 Backend: http://{HOST}:{PORT}")
        print(f"📍 Point your domain to: {HOST}:3000 (when frontend is ready)")
        print(f"⚠️  This is a demo - full app requires FastAPI dependencies")
        print(f"🛑 Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print(f"\n👋 Sara Hub demo stopped")
            httpd.shutdown()