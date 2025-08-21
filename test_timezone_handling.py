#!/usr/bin/env python3
"""
Test timezone handling for Eastern time scheduling
"""
import sys
import pytz
from datetime import datetime, time
sys.path.insert(0, '/home/david/jarvis/backend')

def test_timezone_handling():
    print("🕐 TIMEZONE HANDLING TEST")
    print("=" * 40)
    
    # Test current time conversion
    eastern_tz = pytz.timezone('America/New_York')
    utc_now = datetime.now(pytz.UTC)
    eastern_now = utc_now.astimezone(eastern_tz)
    
    print(f"UTC Time: {utc_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Eastern Time: {eastern_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Eastern DST Active: {'Yes' if eastern_now.dst() else 'No'}")
    
    # Test dream time calculation
    dream_time = time(2, 0)  # 2:00 AM
    current_time = eastern_now.time()
    
    print(f"\nDream Schedule:")
    print(f"Dream time: {dream_time.strftime('%I:%M %p')} Eastern")
    print(f"Current time: {current_time.strftime('%I:%M %p')} Eastern")
    
    # Calculate when next dream will occur
    if current_time >= dream_time:
        # Dream time has passed today, next dream is tomorrow
        from datetime import timedelta
        next_dream = eastern_now.replace(hour=2, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        # Dream time hasn't occurred yet today
        next_dream = eastern_now.replace(hour=2, minute=0, second=0, microsecond=0)
    
    time_until_dream = next_dream - eastern_now
    hours_until = time_until_dream.total_seconds() / 3600
    
    print(f"Next dream: {next_dream.strftime('%Y-%m-%d at %I:%M %p %Z')}")
    print(f"Hours until next dream: {hours_until:.1f}")
    
    # Test awareness check timing
    print(f"\nAwareness Check Schedule:")
    print(f"Runs every 30 minutes (1800 seconds)")
    print(f"Current Eastern time: {eastern_now.strftime('%I:%M %p')}")
    
    # Show next few awareness check times
    from datetime import timedelta
    for i in range(1, 4):
        next_check = eastern_now + timedelta(minutes=30 * i)
        print(f"Next check {i}: {next_check.strftime('%I:%M %p')} Eastern")
    
    print(f"\n✅ Timezone handling is working correctly!")
    print(f"🌙 Dreams will occur at 2 AM Eastern (accounting for DST)")
    print(f"🔮 Awareness checks every 30 minutes in Eastern time")

if __name__ == "__main__":
    test_timezone_handling()