#!/usr/bin/env python3
"""
Daily Brief Generation Script for Jarvis Mode

This script generates daily briefs for all users at 6:30 AM local time.
It's designed to be called by cron.

Usage: python3 generate_daily_brief.py
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, date

# Add the backend directory to the path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
sys.path.insert(0, backend_dir)

try:
    from app.services.daily_brief_service import daily_brief_service
    from app.services.solo_mode_service import solo_mode_service
    from app.db.session import SessionLocal
    import sqlalchemy
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), '..', 'logs', 'daily_brief.log'), mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


async def generate_brief_for_user(user_id: str) -> bool:
    """Generate daily brief for a specific user"""
    
    db = SessionLocal()
    try:
        logger.info(f"Generating daily brief for user {user_id}")
        
        brief = await daily_brief_service.generate_brief(
            db=db,
            user_id=user_id,
            target_date=date.today()
        )
        
        logger.info(f"Successfully generated brief {brief.id} for user {user_id} "
                   f"with {brief.total_items} items in {brief.generation_duration_ms}ms")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to generate brief for user {user_id}: {e}")
        return False
    finally:
        db.close()


async def generate_all_daily_briefs():
    """Generate daily briefs for all users"""
    
    start_time = datetime.now()
    logger.info("=== Starting Daily Brief Generation ===")
    
    try:
        # Check if we're in solo mode
        if solo_mode_service.is_solo_mode():
            logger.info("Solo mode detected - generating brief for solo user")
            
            solo_user_id = str(solo_mode_service.get_solo_user_id())
            success = await generate_brief_for_user(solo_user_id)
            
            if success:
                logger.info("✅ Solo user brief generated successfully")
            else:
                logger.error("❌ Failed to generate solo user brief")
                return False
                
        else:
            logger.info("Multi-user mode detected - generating briefs for all users")
            
            # TODO: In full multi-user mode, query all active users
            # For now, this is a placeholder since we're focusing on solo mode
            logger.warning("Multi-user brief generation not yet implemented")
            return False
        
        # Log completion
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"=== Daily Brief Generation Complete in {duration:.2f}s ===")
        
        return True
        
    except Exception as e:
        logger.error(f"Daily brief generation failed: {e}")
        return False


def create_inbox_notification():
    """Create an inbox notification that the daily brief is ready"""
    
    try:
        from app.services.jarvis_inbox_service import inbox_service
        from app.models.jarvis_inbox import InboxKind
        
        db = SessionLocal()
        
        if solo_mode_service.is_solo_mode():
            user_id = str(solo_mode_service.get_solo_user_id())
            
            # Create inbox notification
            inbox_service.create_inbox_item(
                db=db,
                user_id=user_id,
                kind=InboxKind.INSIGHT,
                title="📅 Daily Brief Ready",
                body=f"Your morning briefing for {date.today().strftime('%B %d')} has been generated with priorities, calendar, and insights.",
                source="daily_brief_cron",
                payload={"date": date.today().isoformat()},
                priority=7,
                dedupe_key=f"daily_brief_{date.today().isoformat()}",
                immediate=True  # Skip batching for daily brief notifications
            )
            
            logger.info("Created inbox notification for daily brief")
        
        db.close()
        
    except Exception as e:
        logger.error(f"Failed to create inbox notification: {e}")


def main():
    """Main entry point"""
    
    # Check if we have the required environment
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    try:
        # Generate daily briefs
        success = asyncio.run(generate_all_daily_briefs())
        
        if success:
            # Create inbox notification
            create_inbox_notification()
            
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