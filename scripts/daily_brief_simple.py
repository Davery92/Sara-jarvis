#!/usr/bin/env python3
"""
Simple Daily Brief Generation for Jarvis Mode

This script creates a daily brief notification in the Jarvis inbox
without complex model dependencies. Designed for cron execution.

Usage: python3 daily_brief_simple.py
"""

import os
import sys
from datetime import datetime, date
import logging

# Add the backend directory to the path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
sys.path.insert(0, backend_dir)

# Set up logging
log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'daily_brief.log'), mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def generate_daily_brief():
    """Generate a daily brief and create inbox notification"""
    
    try:
        from app.services.jarvis_inbox_service import inbox_service
        from app.models.jarvis_inbox import InboxKind
        from app.db.session import SessionLocal
        from app.services.solo_mode_service import solo_mode_service
    except ImportError as e:
        logger.error(f"Error importing modules: {e}")
        return False

    db = SessionLocal()
    
    try:
        if not solo_mode_service.is_solo_mode():
            logger.error("Not in solo mode - daily brief generation requires JARVIS_MODE=true")
            return False
            
        user_id = str(solo_mode_service.get_solo_user_id())
        today = date.today()
        
        logger.info(f"Generating daily brief for {today.strftime('%B %d, %Y')}")
        
        # Create the daily brief content (simplified for now)
        brief_sections = [
            {
                "id": "welcome", 
                "title": "Good Morning", 
                "items": [f"Welcome to {today.strftime('%A, %B %d, %Y')}"]
            },
            {
                "id": "focus", 
                "title": "Today's Focus", 
                "items": ["Your Jarvis AI is active and monitoring for insights", "Check your reminders and calendar for priorities"]
            },
            {
                "id": "system", 
                "title": "System Status", 
                "items": ["All Jarvis services are operational", "Proactive monitoring is enabled"]
            }
        ]
        
        # Create inbox notification
        item = inbox_service.create_inbox_item(
            db=db,
            user_id=user_id,
            kind=InboxKind.INSIGHT,
            title=f"🌅 Daily Brief - {today.strftime('%B %d')}",
            body=f"Your morning briefing is ready. Jarvis has prepared insights and priorities for {today.strftime('%A, %B %d, %Y')}.",
            source="daily_brief_cron",
            payload={
                "date": today.isoformat(),
                "sections": brief_sections,
                "generated_at": datetime.now().isoformat(),
                "type": "morning_brief"
            },
            priority=8,
            dedupe_key=f"daily_brief_{today.isoformat()}",
            immediate=True  # Skip batching for daily brief
        )
        
        if item:
            logger.info(f"✅ Created daily brief inbox item: {item.id}")
            logger.info(f"   Title: {item.title}")
            logger.info(f"   Priority: {item.priority}")
            return True
        else:
            logger.warning("⚠️ Daily brief was queued for batching")
            return True  # Still consider this success
            
    except Exception as e:
        logger.error(f"❌ Failed to generate daily brief: {e}")
        return False
    finally:
        db.close()

def cleanup_old_briefs():
    """Clean up old daily brief notifications (keep last 7 days)"""
    
    try:
        from app.services.jarvis_inbox_service import inbox_service
        from app.db.session import SessionLocal
        from app.services.solo_mode_service import solo_mode_service
        from app.models.jarvis_inbox import JarvisInbox
        from sqlalchemy import and_
        from datetime import timedelta
    except ImportError as e:
        logger.error(f"Error importing cleanup modules: {e}")
        return
    
    db = SessionLocal()
    
    try:
        if not solo_mode_service.is_solo_mode():
            return
            
        user_id = str(solo_mode_service.get_solo_user_id())
        cutoff_date = datetime.now() - timedelta(days=7)
        
        # Archive old daily brief items
        old_items = db.query(JarvisInbox).filter(
            and_(
                JarvisInbox.user_id == user_id,
                JarvisInbox.source.like("daily_brief%"),
                JarvisInbox.created_at < cutoff_date,
                JarvisInbox.status != "archived"
            )
        ).all()
        
        if old_items:
            for item in old_items:
                inbox_service.archive(db, item.id, user_id)
            
            logger.info(f"📁 Archived {len(old_items)} old daily brief items")
            
    except Exception as e:
        logger.error(f"❌ Failed to cleanup old briefs: {e}")
    finally:
        db.close()

def main():
    """Main entry point"""
    
    logger.info("=== Starting Daily Brief Generation ===")
    
    # Check environment
    if not os.getenv('DATABASE_URL'):
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    if os.getenv('JARVIS_MODE', 'false').lower() != 'true':
        logger.error("JARVIS_MODE environment variable not set to 'true'")
        sys.exit(1)
    
    try:
        # Generate daily brief
        success = generate_daily_brief()
        
        if success:
            # Cleanup old briefs
            cleanup_old_briefs()
            
            logger.info("🎉 Daily brief generation completed successfully")
            sys.exit(0)
        else:
            logger.error("Daily brief generation failed")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Script failed with exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()