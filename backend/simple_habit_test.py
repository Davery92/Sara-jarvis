#!/usr/bin/env python3
"""
Simple test for habit tracking system using Bearer token auth
"""

import requests
import json

# Configuration
BASE_URL = "http://10.185.1.180:8000"
EMAIL = "david@avery.cloud"
PASSWORD = "Nutman17!"

def get_auth_token():
    """Get JWT token from login"""
    response = requests.post(f"{BASE_URL}/auth/login", json={
        "email": EMAIL,
        "password": PASSWORD
    })
    
    if response.status_code == 200:
        data = response.json()
        if "access_token" in data:
            return data["access_token"]
    
    print(f"Login failed: {response.status_code}")
    return None

def make_request(method, url, token, **kwargs):
    """Make authenticated request"""
    headers = {"Authorization": f"Bearer {token}"}
    if method.upper() == "GET":
        return requests.get(url, headers=headers, **kwargs)
    elif method.upper() == "POST":
        return requests.post(url, headers=headers, **kwargs)

def test_habit_system():
    """Test habit system end-to-end"""
    print("🧪 Testing Habit System...")
    
    # Login
    token = get_auth_token()
    if not token:
        print("❌ Failed to authenticate")
        return
    
    print("✅ Logged in successfully")
    
    # Create a binary habit
    print("\n🎯 Creating binary habit...")
    binary_habit = {
        "title": "Daily Meditation",
        "type": "binary", 
        "rrule": "FREQ=DAILY",
        "notes": "10 minutes of mindfulness"
    }
    
    response = make_request("POST", f"{BASE_URL}/habits", token, json=binary_habit)
    if response.status_code == 200:
        habit_id = response.json()["id"]
        print(f"✅ Binary habit created: {habit_id}")
    else:
        print(f"❌ Failed to create habit: {response.status_code} - {response.text}")
        return
    
    # Create a quantitative habit  
    print("\n💧 Creating quantitative habit...")
    quant_habit = {
        "title": "Drink Water",
        "type": "quantitative",
        "target_numeric": 64,
        "unit": "oz",
        "rrule": "FREQ=DAILY"
    }
    
    response = make_request("POST", f"{BASE_URL}/habits", token, json=quant_habit)
    if response.status_code == 200:
        water_habit_id = response.json()["id"]
        print(f"✅ Quantitative habit created: {water_habit_id}")
    else:
        print(f"❌ Failed to create quantitative habit: {response.text}")
        water_habit_id = None
    
    # List all habits
    print("\n📋 Listing all habits...")
    response = make_request("GET", f"{BASE_URL}/habits", token)
    if response.status_code == 200:
        habits = response.json()
        print(f"✅ Found {len(habits)} habits:")
        for habit in habits:
            print(f"   - {habit['title']} ({habit['type']})")
    else:
        print(f"❌ Failed to list habits: {response.text}")
    
    # Get today's habits
    print("\n📅 Getting today's habits...")
    response = make_request("GET", f"{BASE_URL}/habits/today", token)
    if response.status_code == 200:
        today_habits = response.json()
        print(f"✅ Found {len(today_habits)} habits for today:")
        for habit in today_habits:
            print(f"   - {habit['title']}: {habit['status']} (Progress: {habit['progress']:.0%})")
    else:
        print(f"❌ Failed to get today's habits: {response.text}")
    
    # Log binary habit completion
    print(f"\n📝 Logging binary habit completion...")
    response = make_request("POST", f"{BASE_URL}/habits/{habit_id}/log", token, json={"source": "manual"})
    if response.status_code == 200:
        print("✅ Binary habit logged successfully")
    else:
        print(f"❌ Failed to log binary habit: {response.text}")
    
    # Log quantitative habit progress
    if water_habit_id:
        print(f"\n💧 Logging water intake...")
        response = make_request("POST", f"{BASE_URL}/habits/{water_habit_id}/log", token, json={
            "amount": 16,
            "source": "manual"
        })
        if response.status_code == 200:
            print("✅ Water logged successfully")
            
            # Log more water
            response = make_request("POST", f"{BASE_URL}/habits/{water_habit_id}/log", token, json={
                "amount": 24,
                "source": "manual"
            })
            if response.status_code == 200:
                print("✅ More water logged successfully")
        else:
            print(f"❌ Failed to log water: {response.text}")
    
    # Check streak
    print(f"\n🔥 Checking streak for binary habit...")
    response = make_request("GET", f"{BASE_URL}/habits/{habit_id}/streak", token)
    if response.status_code == 200:
        streak = response.json()
        print(f"✅ Streak: Current={streak['current_streak']}, Best={streak['best_streak']}")
    else:
        print(f"❌ Failed to get streak: {response.text}")
    
    # Check today's habits again to see progress
    print("\n📅 Checking today's habits after logging...")
    response = make_request("GET", f"{BASE_URL}/habits/today", token)
    if response.status_code == 200:
        today_habits = response.json()
        print(f"✅ Today's habits after logging:")
        for habit in today_habits:
            total = f" ({habit['total_amount']}/{habit['target']} {habit['unit']})" if habit.get('total_amount') is not None else ""
            print(f"   - {habit['title']}: {habit['status']} (Progress: {habit['progress']:.0%}){total}")
    else:
        print(f"❌ Failed to get updated today's habits: {response.text}")
    
    print("\n🎉 Test completed!")

if __name__ == "__main__":
    test_habit_system()