#!/usr/bin/env python3
"""
Test script to verify the habit tracking frontend integration with backend APIs
"""

import requests
import json
import time
import os

# Configuration
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

def test_frontend_backend_integration():
    print("🧪 Testing Habit Frontend-Backend Integration...")
    
    # Test 1: Login and get token
    print("\n1. Testing Authentication...")
    login_response = requests.post(f"{BASE_URL}/auth/login", json={
        "email": "david@avery.cloud",
        "password": "Nutman17!"
    })
    
    if login_response.status_code == 200:
        token = login_response.json()["access_token"]
        print("✅ Authentication successful")
        headers = {"Authorization": f"Bearer {token}"}
    else:
        print(f"❌ Authentication failed: {login_response.status_code}")
        return False
    
    # Test 2: Test /habits/today endpoint (main frontend endpoint)
    print("\n2. Testing Today's Habits API...")
    today_response = requests.get(f"{BASE_URL}/habits/today", headers=headers)
    
    if today_response.status_code == 200:
        today_data = today_response.json()
        print(f"✅ Today's habits API working: {len(today_data)} habits found")
        if today_data:
            print(f"   Sample habit: {today_data[0]['title']} ({today_data[0]['status']})")
    else:
        print(f"❌ Today's habits API failed: {today_response.status_code}")
        return False
    
    # Test 3: Test habit creation API
    print("\n3. Testing Habit Creation API...")
    new_habit = {
        "title": "Frontend Test Habit",
        "type": "binary",
        "rrule": "FREQ=DAILY",
        "grace_days": 0,
        "retro_hours": 24,
        "notes": "Created from frontend integration test"
    }
    
    create_response = requests.post(f"{BASE_URL}/habits", json=new_habit, headers=headers)
    
    if create_response.status_code == 200:
        created_habit = create_response.json()
        habit_id = created_habit["id"]
        print(f"✅ Habit creation successful: {habit_id}")
    else:
        print(f"❌ Habit creation failed: {create_response.status_code}")
        print(f"   Response: {create_response.text}")
        return False
    
    # Test 4: Test habit logging API
    print("\n4. Testing Habit Logging API...")
    log_response = requests.post(f"{BASE_URL}/habits/{habit_id}/log", json={}, headers=headers)
    
    if log_response.status_code == 200:
        print("✅ Habit logging successful")
    else:
        print(f"❌ Habit logging failed: {log_response.status_code}")
        print(f"   Response: {log_response.text}")
    
    # Test 5: Test insights API
    print("\n5. Testing Insights API...")
    insights_response = requests.get(f"{BASE_URL}/insights/habits", headers=headers)
    
    if insights_response.status_code == 200:
        insights_data = insights_response.json()
        print(f"✅ Insights API working")
        print(f"   Total habits: {insights_data.get('total_habits', 'N/A')}")
        print(f"   Completion rate: {insights_data.get('average_completion_rate', 'N/A')}%")
    else:
        print(f"❌ Insights API failed: {insights_response.status_code}")
        print(f"   Response: {insights_response.text}")
    
    # Test 6: Test worker status API
    print("\n6. Testing Worker Status API...")
    worker_response = requests.get(f"{BASE_URL}/workers/status", headers=headers)
    
    if worker_response.status_code == 200:
        worker_data = worker_response.json()
        print("✅ Worker status API working")
        print(f"   Workers running: {worker_data.get('running', False)}")
        print(f"   Available workers: {list(worker_data.get('workers', {}).keys())}")
    else:
        print(f"❌ Worker status API failed: {worker_response.status_code}")
    
    # Test 7: Test frontend accessibility
    print("\n7. Testing Frontend Accessibility...")
    try:
        frontend_response = requests.get(FRONTEND_URL, timeout=5)
        if frontend_response.status_code == 200:
            print("✅ Frontend is accessible")
            
            # Check if it contains our habit components
            if "habits" in frontend_response.text.lower():
                print("✅ Frontend contains habit-related content")
            else:
                print("⚠️ Frontend may not have habit content loaded")
        else:
            print(f"❌ Frontend not accessible: {frontend_response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Frontend connection failed: {e}")
    
    # Clean up: Delete the test habit
    print("\n8. Cleaning up test data...")
    delete_response = requests.delete(f"{BASE_URL}/habits/{habit_id}", headers=headers)
    if delete_response.status_code == 200:
        print("✅ Test habit cleaned up")
    else:
        print(f"⚠️ Could not clean up test habit: {delete_response.status_code}")
    
    print("\n🎉 Frontend-Backend Integration Test Complete!")
    print("\nNext steps:")
    print(f"1. Visit {FRONTEND_URL} to test the frontend")
    print("2. Log in with your credentials")
    print("3. Navigate to the 'Habits' section")
    print("4. Test creating habits, logging progress, and viewing insights")
    
    return True

if __name__ == "__main__":
    test_frontend_backend_integration()
