#!/usr/bin/env python3
"""
Simple test script to create a daily brief manually

This tests the Jarvis inbox system without the complex daily brief service.
"""

import os
import sys
from datetime import datetime, date

# Add the backend directory to the path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
sys.path.insert(0, backend_dir)

try:
    from app.services.jarvis_inbox_service import inbox_service
    from app.models.jarvis_inbox import InboxKind
    from app.db.session import SessionLocal
    from app.services.solo_mode_service import solo_mode_service
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

def create_sample_brief():
    """Create a sample daily brief notification"""
    
    db = SessionLocal()
    
    try:
        if solo_mode_service.is_solo_mode():
            user_id = str(solo_mode_service.get_solo_user_id())
            print(f"Creating daily brief for solo user {user_id}")
            
            # Create inbox notification
            item = inbox_service.create_inbox_item(
                db=db,
                user_id=user_id,
                kind=InboxKind.INSIGHT,
                title="🌅 Daily Brief Ready",
                body=f"Your morning briefing for {date.today().strftime('%B %d, %Y')} has been generated. Start your day with confidence knowing your priorities are aligned.",
                source="daily_brief_test",
                payload={
                    "date": date.today().isoformat(),
                    "sections": [
                        {"id": "priorities", "title": "Top Priorities", "items": ["Review project status", "Prepare for team meeting"]},
                        {"id": "calendar", "title": "Calendar Overview", "items": ["No conflicts detected", "Next meeting: 10:00 AM"]},
                        {"id": "focus", "title": "Suggested Focus", "items": ["Deep work block: 9-11 AM"]}
                    ]
                },
                priority=8,
                dedupe_key=f"daily_brief_{date.today().isoformat()}",
                immediate=True
            )
            
            if item:
                print(f"✅ Created daily brief inbox item: {item.id}")
                print(f"   Title: {item.title}")
                print(f"   Priority: {item.priority}")
                print(f"   Status: {item.status}")
            else:
                print("⚠️ Item was queued for batching")
                
        else:
            print("❌ Not in solo mode")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()

def test_inbox_stats():
    """Test inbox statistics"""
    
    db = SessionLocal()
    
    try:
        if solo_mode_service.is_solo_mode():
            user_id = str(solo_mode_service.get_solo_user_id())
            
            unread = inbox_service.get_unread_count(db, user_id)
            items = inbox_service.get_inbox_items(db, user_id, limit=5)
            
            print(f"📊 Inbox Stats:")
            print(f"   Unread: {unread}")
            print(f"   Recent items: {len(items)}")
            
            for item in items:
                print(f"   - {item.title} ({item.status})")
                
    except Exception as e:
        print(f"❌ Error getting stats: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("=== Jarvis Daily Brief Test ===")
    
    create_sample_brief()
    test_inbox_stats()
    
    print("=== Test Complete ===")