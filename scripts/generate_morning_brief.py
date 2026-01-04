#!/usr/bin/env python3
"""
Morning Brief Generation Script

Generates morning briefs for all active users at 5 AM.
Run via cron:
    0 5 * * * DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub" python3 /home/david/jarvis/scripts/generate_morning_brief.py >> /home/david/jarvis/logs/morning_brief.log 2>&1

"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# Set environment variables if not present
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
if "OPENAI_BASE_URL" not in os.environ:
    os.environ["OPENAI_BASE_URL"] = "http://100.104.68.115:11434/v1"
if "OPENAI_MODEL" not in os.environ:
    os.environ["OPENAI_MODEL"] = "gpt-oss:120b"
if "OPENAI_API_KEY" not in os.environ:
    os.environ["OPENAI_API_KEY"] = "dummy"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("morning_brief_generator")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.morning_brief_service import morning_brief_service


def get_active_users(session) -> list:
    """Get list of active user IDs."""
    result = session.execute(text("""
        SELECT id FROM users
        WHERE is_active = true OR is_active IS NULL
    """))
    return [str(row.id) for row in result.fetchall()]


async def generate_briefs_for_all_users():
    """Generate morning briefs for all active users."""
    logger.info("=" * 60)
    logger.info(f"Starting morning brief generation at {datetime.now()}")
    logger.info("=" * 60)

    # Create database connection
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = SessionLocal()

    try:
        # Get all active users
        users = get_active_users(session)
        logger.info(f"Found {len(users)} active users")

        success_count = 0
        error_count = 0

        for user_id in users:
            try:
                logger.info(f"Generating brief for user: {user_id}")
                brief = await morning_brief_service.generate_brief(user_id, session)
                logger.info(f"Successfully generated brief for {user_id}")
                logger.info(f"  - News sources: {len(brief.news_sources or [])}")
                logger.info(f"  - Calendar events: {len(brief.calendar_events or [])}")
                logger.info(f"  - Audio duration: {brief.audio_duration_seconds or 'N/A'}s")
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to generate brief for {user_id}: {e}")
                error_count += 1

        logger.info("=" * 60)
        logger.info(f"Morning brief generation complete")
        logger.info(f"  - Successful: {success_count}")
        logger.info(f"  - Errors: {error_count}")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Fatal error in morning brief generation: {e}")
        raise

    finally:
        session.close()


def main():
    """Main entry point."""
    try:
        asyncio.run(generate_briefs_for_all_users())
    except KeyboardInterrupt:
        logger.info("Generation interrupted by user")
    except Exception as e:
        logger.error(f"Morning brief generation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
