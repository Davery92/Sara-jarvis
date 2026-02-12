#!/usr/bin/env python3
"""
Morning Brief Generation Script

Generates the morning brief for the configured solo user at 6 AM ET.
Run via cron:
    0 6 * * * SOLO_USER_ID=64f37c56-85cb-4590-8de9-adfc17d343ed DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub" /usr/bin/python3 /home/david/jarvis/scripts/generate_morning_brief.py >> /home/david/jarvis/logs/morning_brief.log 2>&1

Push notification is sent automatically when brief is ready (via notification_service).
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

# Solo user — only generate for David
SOLO_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")


async def generate_brief():
    """Generate morning brief for the solo user."""
    logger.info("=" * 60)
    logger.info(f"Starting morning brief generation at {datetime.now()}")
    logger.info(f"Solo user: {SOLO_USER_ID}")
    logger.info("=" * 60)

    # Create database connection
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = SessionLocal()

    try:
        logger.info(f"Generating brief for user: {SOLO_USER_ID}")
        brief = await morning_brief_service.generate_brief(SOLO_USER_ID, session)
        logger.info(f"Successfully generated brief for {SOLO_USER_ID}")
        logger.info(f"  - News sources: {len(brief.news_sources or [])}")
        logger.info(f"  - Calendar events: {len(brief.calendar_events or [])}")
        logger.info(f"  - Audio duration: {brief.audio_duration_seconds or 'N/A'}s")

        logger.info("=" * 60)
        logger.info("Morning brief generation complete")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Failed to generate brief: {e}")
        raise

    finally:
        session.close()


def main():
    """Main entry point."""
    try:
        asyncio.run(generate_brief())
    except KeyboardInterrupt:
        logger.info("Generation interrupted by user")
    except Exception as e:
        logger.error(f"Morning brief generation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
