#!/usr/bin/env python3
"""Test the habits API with proper format"""

import requests
import json

BASE_URL = "http://10.185.1.180:8000"

# Login
login_data = {
    "email": "david@avery.cloud", 
    "password": "Nutman17!"
}

login_response = requests.post(f"{BASE_URL}/auth/login", json=login_data)
print(f"Login status: {login_response.status_code}")

if login_response.status_code == 200:
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # Test habits/today
    today_response = requests.get(f"{BASE_URL}/habits/today", headers=headers)
    print(f"Today's habits status: {today_response.status_code}")
    
    if today_response.status_code == 200:
        data = today_response.json()
        print("✅ API Response Structure:")
        print(f"  Date: {data.get('date')}")
        print(f"  Habits count: {len(data.get('habits', []))}")
        print(f"  Stats: {data.get('stats')}")
        
        if data.get('habits'):
            print("  Sample habit:")
            habit = data['habits'][0]
            print(f"    Title: {habit.get('title')}")
            print(f"    Type: {habit.get('type')}")
            print(f"    Status: {habit.get('status')}")
            print(f"    Progress: {habit.get('progress')}")
    else:
        print(f"❌ Error: {today_response.text}")
else:
    print(f"❌ Login failed: {login_response.text}")