#!/usr/bin/env python3
"""
Test script to manually trigger the dreaming service and generate insights
"""

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, '/home/david/jarvis/backend')

from app.main_simple import dreaming_service
from app.db.session import SessionLocal
from app.models.user import User

async def test_dream_cycle():
    """Test the dream cycle for available users"""
    print("🧪 Testing dream cycle...")
    
    # Get users from database
    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    
    if not users:
        print("❌ No users found in database")
        return
    
    print(f"👥 Found {len(users)} users")
    
    for user in users:
        print(f"\n🌙 Testing dream cycle for user: {user.email}")
        try:
            await dreaming_service.dream_cycle(user.id, min_episodes=1)
            print(f"✅ Dream cycle completed for {user.email}")
        except Exception as e:
            print(f"❌ Dream cycle failed for {user.email}: {e}")
    
    print("\n🎉 Dream cycle test complete!")

if __name__ == "__main__":
    asyncio.run(test_dream_cycle())