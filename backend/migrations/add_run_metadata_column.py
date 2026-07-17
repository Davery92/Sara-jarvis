"""
Add run_metadata JSONB column to agent_run_log.

Stores structured per-run data (context completeness, token counts, stale domains)
separately from the human-readable context_summary field, enabling dashboards
and automated quality monitoring.
"""

import os
import logging
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sara:sara123@10.185.1.180:5432/sara_hub")


def migrate():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE agent_run_log
            ADD COLUMN IF NOT EXISTS run_metadata JSONB DEFAULT '{}'::jsonb;
        """))
        conn.commit()
        logger.info("Added run_metadata column to agent_run_log")


if __name__ == "__main__":
    migrate()
