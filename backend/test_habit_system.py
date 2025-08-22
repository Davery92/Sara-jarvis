#!/usr/bin/env python3
"""
Test script for habit tracking system
"""

import requests
import json
from datetime import datetime

# Configuration
BASE_URL = "http://10.185.1.180:8000"
EMAIL = "david@avery.cloud"
PASSWORD = "Nutman17!"

def login():
    """Login and get session token"""
    response = requests.post(f"{BASE_URL}/auth/login", json={
        "email": EMAIL,
        "password": PASSWORD
    })
    
    if response.status_code == 200:
        # Try to extract session token from cookies first
        session_token = None
        for cookie in response.cookies:
            if cookie.name == "session_token":
                session_token = cookie.value
                break
        
        if session_token:
            return {"session_token": session_token}
        
        # If no cookie, try to get from response body
        try:
            data = response.json()
            if "access_token" in data:
                # Use Authorization header for this implementation
                return {"Authorization": f"Bearer {data['access_token']}"}
        except:
            pass
    
    print(f"Login failed: {response.status_code} - {response.text}")
    return None

def test_habit_creation(auth):
    """Test creating different types of habits"""
    print("🎯 Testing habit creation...")
    
    # Binary habit
    binary_habit = {
        "title": "Daily Meditation",
        "type": "binary",
        "rrule": "FREQ=DAILY",
        "notes": "10 minutes of mindfulness"
    }
    
    if "Authorization" in auth:
        response = requests.post(f"{BASE_URL}/habits", json=binary_habit, headers=auth)
    else:
        response = requests.post(f"{BASE_URL}/habits", json=binary_habit, cookies=auth)
    
    if response.status_code == 200:
        print("✅ Binary habit created successfully")
        return response.json()["id"]
    else:
        print(f"❌ Failed to create binary habit: {response.text}")
        return None

def test_quantitative_habit(cookies):
    """Test creating a quantitative habit"""
    print("💧 Testing quantitative habit creation...")
    
    quant_habit = {
        "title": "Drink Water",
        "type": "quantitative", 
        "target_numeric": 64,
        "unit": "oz",
        "rrule": "FREQ=DAILY",
        "windows": json.dumps([
            {"name": "Morning", "start": "06:00", "end": "12:00"},
            {"name": "Afternoon", "start": "12:00", "end": "18:00"}
        ])
    }
    
    response = requests.post(f"{BASE_URL}/habits", json=quant_habit, cookies=cookies)
    if response.status_code == 200:
        print("✅ Quantitative habit created successfully")
        return response.json()["id"]
    else:
        print(f"❌ Failed to create quantitative habit: {response.text}")
        return None

def test_today_habits(cookies):
    """Test getting today's habits"""
    print("📅 Testing today's habits endpoint...")
    
    response = requests.get(f"{BASE_URL}/habits/today", cookies=cookies)
    if response.status_code == 200:
        habits = response.json()
        print(f"✅ Found {len(habits)} habits for today")
        for habit in habits:
            print(f"   - {habit['title']} ({habit['type']}) - Status: {habit['status']}")
        return habits
    else:
        print(f"❌ Failed to get today's habits: {response.text}")
        return []

def test_habit_logging(cookies, habit_id, habit_type="binary"):
    """Test logging habit completion"""
    print(f"📝 Testing habit logging for {habit_type}...")
    
    if habit_type == "binary":
        log_data = {"source": "manual"}
    elif habit_type == "quantitative":
        log_data = {"amount": 16, "source": "manual"}
    else:
        log_data = {"source": "manual"}
    
    response = requests.post(f"{BASE_URL}/habits/{habit_id}/log", json=log_data, cookies=cookies)
    if response.status_code == 200:
        print("✅ Habit logged successfully")
        return True
    else:
        print(f"❌ Failed to log habit: {response.text}")
        return False

def test_habit_streak(cookies, habit_id):
    """Test getting habit streak"""
    print("🔥 Testing habit streak endpoint...")
    
    response = requests.get(f"{BASE_URL}/habits/{habit_id}/streak", cookies=cookies)
    if response.status_code == 200:
        streak = response.json()
        print(f"✅ Streak info: Current={streak['current_streak']}, Best={streak['best_streak']}")
        return streak
    else:
        print(f"❌ Failed to get streak: {response.text}")
        return None

def test_list_habits(cookies):
    """Test listing all habits"""
    print("📋 Testing list habits endpoint...")
    
    response = requests.get(f"{BASE_URL}/habits", cookies=cookies)
    if response.status_code == 200:
        habits = response.json()
        print(f"✅ Found {len(habits)} total habits")
        return habits
    else:
        print(f"❌ Failed to list habits: {response.text}")
        return []

def main():
    """Run all tests"""
    print("🧪 Starting Habit System Tests...")
    print("=" * 50)
    
    # Login
    cookies = login()
    if not cookies:
        print("❌ Cannot continue without authentication")
        return
    
    print("✅ Logged in successfully")
    print()
    
    # Test habit creation
    binary_habit_id = test_habit_creation(cookies)
    quant_habit_id = test_quantitative_habit(cookies)
    print()
    
    # Test listing habits
    test_list_habits(cookies)
    print()
    
    # Test today's habits
    today_habits = test_today_habits(cookies)
    print()
    
    # Test logging if we have habits
    if binary_habit_id:
        test_habit_logging(cookies, binary_habit_id, "binary")
        test_habit_streak(cookies, binary_habit_id)
        print()
    
    if quant_habit_id:
        test_habit_logging(cookies, quant_habit_id, "quantitative")
        # Log again to see progress accumulation
        test_habit_logging(cookies, quant_habit_id, "quantitative")
        test_habit_streak(cookies, quant_habit_id)
        print()
    
    # Test today's habits again to see updates
    print("📅 Testing today's habits after logging...")
    test_today_habits(cookies)
    
    print()
    print("🎉 All tests completed!")

if __name__ == "__main__":
    main()