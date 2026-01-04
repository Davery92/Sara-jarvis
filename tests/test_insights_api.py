#!/usr/bin/env python3
"""Test the updated insights API"""

import requests
import json
import os

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

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
    
    # Test insights API
    insights_response = requests.get(f"{BASE_URL}/insights/habits?period=month", headers=headers)
    print(f"Insights API status: {insights_response.status_code}")
    
    if insights_response.status_code == 200:
        data = insights_response.json()
        print("✅ API Response Structure:")
        print(f"  Overview: {list(data.get('overview', {}).keys())}")
        print(f"  Weekly Stats: {list(data.get('weekly_stats', {}).keys())}")
        print(f"  Habit Performance count: {len(data.get('habit_performance', []))}")
        print(f"  Patterns: {list(data.get('patterns', {}).keys())}")
        
        print("\nOverview stats:")
        overview = data.get('overview', {})
        print(f"  Total habits: {overview.get('total_habits')}")
        print(f"  Average completion rate: {overview.get('average_completion_rate')}%")
        print(f"  Current streaks: {overview.get('current_streaks')}")
        
    else:
        print(f"❌ Error: {insights_response.text}")
else:
    print(f"❌ Login failed: {login_response.text}")
