# Sara Fitness Module - Testing Guide

## 🎯 Quick Start Testing

The Sara Fitness module is **COMPLETE** and ready for testing. Here's how to verify everything works:

## 📋 Prerequisites

### Dependencies Check
The fitness system uses standard packages. If you can run the existing Sara backend, you have what you need:
- FastAPI, SQLAlchemy, Alembic (for API and database)  
- psycopg, Redis, httpx (for data and external services)
- Pydantic (for validation)

### Environment Setup
Make sure your environment variables are set (same as existing Sara setup):
```bash
export DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
export REDIS_URL="redis://redis:6379/0" 
```

## 🚀 Step 1: Start the Server

```bash
cd /home/david/Sara-jarvis/backend
python3 app/main_simple.py
```

The fitness routes will be available at `/fitness/*` endpoints.

## 🧪 Step 2: Test Core Endpoints

### Health Check
```bash
# Test that fitness routes are registered
curl -X GET "http://localhost:8000/fitness/notifications/schedule" \
  -H "accept: application/json"
```
**Expected**: JSON response with notification schedule information

### Manual Entry Templates
```bash  
# Get readiness assessment form template
curl -X GET "http://localhost:8000/fitness/manual-entry/template/readiness" \
  -H "accept: application/json"
```
**Expected**: Form template with energy, soreness, stress fields

### HealthKit Configuration
```bash
# Get HealthKit setup configuration for iOS
curl -X GET "http://localhost:8000/fitness/healthkit/config" \
  -H "accept: application/json"
```
**Expected**: HealthKit permissions and setup instructions

## 🔐 Step 3: Test with Authentication

Most endpoints require user authentication. Get a token by logging in first:

```bash
# Login to get auth token
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "your@email.com", "password": "yourpassword"}'
```

Then use the token for authenticated requests:
```bash
# Test baseline status (requires auth)
curl -X GET "http://localhost:8000/fitness/baselines/status" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 🏋️ Step 4: Test Fitness Onboarding

### Start Onboarding
```bash
curl -X POST "http://localhost:8000/fitness/onboarding/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"flow_type": "new_journey"}'
```
**Expected**: First onboarding question with session ID

### Continue Onboarding
```bash
curl -X POST "http://localhost:8000/fitness/onboarding/SESSION_ID/continue" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"response": {"choice": "Yes, let'\''s do this!"}}'
```
**Expected**: Next question in the onboarding flow

## 📊 Step 5: Test Daily Readiness System

### Submit Daily Readiness
```bash
curl -X POST "http://localhost:8000/fitness/readiness/daily" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "energy": 4,
    "soreness": 2,
    "stress": 3,
    "time_available_min": 60,
    "hrv_ms": 45,
    "rhr": 58,
    "sleep_hours": 7.5
  }'
```
**Expected**: Readiness score and workout adjustments

### Check Today's Readiness
```bash
curl -X GET "http://localhost:8000/fitness/readiness/today" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
**Expected**: Whether today's readiness has been submitted

## 🔧 Step 6: Test Manual Entry System

### Create Manual Readiness Entry
```bash
curl -X POST "http://localhost:8000/fitness/manual-entry" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "entry_type": "readiness",
    "data": {
      "energy": 3,
      "soreness": 4,
      "stress": 2,
      "time_available_min": 45,
      "notes": "Feeling a bit tired today"
    }
  }'
```
**Expected**: Success confirmation with entry ID

### Get Manual Entry History
```bash
curl -X GET "http://localhost:8000/fitness/manual-entry/history/readiness?days=7" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
**Expected**: List of recent manual entries

## 📱 Step 7: Test HealthKit Integration

### Submit HealthKit Data (simulated)
```bash
curl -X POST "http://localhost:8000/fitness/healthkit/data" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "date": "2025-09-02",
    "metrics": {
      "hrv_ms": 42.5,
      "rhr": 56,
      "sleep_hours": 8.2
    }
  }'
```
**Expected**: Processing confirmation with trend data

### Check HealthKit Sync Status
```bash
curl -X GET "http://localhost:8000/fitness/healthkit/sync-status" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
**Expected**: Sync status and data recency information

## 🎛️ Step 8: Test Adjustment System

### Generate Manual Adjustments
```bash
curl -X POST "http://localhost:8000/fitness/adjustments/generate/WORKOUT_ID?readiness_score=45&time_available_min=30" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
**Expected**: Workout adjustments based on low readiness

### Get Adjustment History
```bash
curl -X GET "http://localhost:8000/fitness/adjustments/history?days=30" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
**Expected**: History of adjustments with analytics

## 🔔 Step 9: Test Notification System

### Setup Notifications
```bash
curl -X POST "http://localhost:8000/fitness/notifications/setup" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
**Expected**: NTFY setup instructions and topic information

### Send Test Notification
```bash
curl -X POST "http://localhost:8000/fitness/notifications/test/readiness_reminder" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"message": "Test readiness reminder"}'
```
**Expected**: Notification sent confirmation

## 📈 Step 10: Test Baseline Learning

### Check Baseline Status
```bash
curl -X GET "http://localhost:8000/fitness/baselines/status" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
**Expected**: Learning status and confidence scores

### Get Baseline History
```bash
curl -X GET "http://localhost:8000/fitness/baselines/history?days=30" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
**Expected**: Baseline learning trends and history

## 🛠️ Troubleshooting

### Common Issues

1. **"Route not found"**
   - Check that fitness routes are registered in main_simple.py
   - Verify the server started without errors

2. **"Authentication required"**
   - Most endpoints need a valid JWT token
   - Login first and use the token in Authorization header

3. **"Database connection error"**
   - Run the fitness migration: `alembic upgrade head`
   - Check DATABASE_URL environment variable

4. **"Redis connection error"**  
   - Check that Redis is running: `docker compose up -d redis`
   - Verify REDIS_URL environment variable

5. **"Import errors on server start"**
   - Check that all dependencies are installed
   - Verify Python path includes the backend directory

### Debug Mode
Start the server with debug logging:
```bash
export PYTHONPATH=/home/david/Sara-jarvis/backend
python3 -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from app.main_simple import app
import uvicorn
uvicorn.run(app, host='0.0.0.0', port=8000, log_level='debug')
"
```

## ✅ Success Indicators

You'll know the fitness system is working correctly when:

1. **Server starts** without import or route registration errors
2. **Health endpoints respond** with proper JSON (notifications/schedule, healthkit/config)  
3. **Onboarding flow works** - you can start and continue through questions
4. **Readiness submission works** - returns scores and adjustments
5. **Manual entry works** - templates load and entries are saved
6. **Baseline learning responds** - shows status and recommendations
7. **Notifications setup works** - returns NTFY configuration

## 🎉 Full System Test

Once basic endpoints work, you can test the complete flow:

1. **Start onboarding** → Complete fitness profile setup
2. **Submit daily readiness** → Get personalized workout adjustments  
3. **Check baseline status** → See learning progress
4. **Setup notifications** → Receive readiness reminders
5. **View adjustment history** → See how recommendations adapt over time

This demonstrates the complete Sara Fitness intelligence system working together!

## 📞 Need Help?

The implementation includes comprehensive error messages and logging. Check:
- Server console output for error details
- FastAPI automatic documentation at `/docs` 
- Individual endpoint responses for specific error messages

The system is designed to be self-documenting and provide clear feedback for troubleshooting.