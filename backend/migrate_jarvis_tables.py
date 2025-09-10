#!/usr/bin/env python3
"""
Migration script for Jarvis Mode tables

This script creates the necessary database tables for Jarvis mode:
- jarvis_inbox: Unified notification system
- daily_briefs: Morning briefing cache
- jarvis_tasks: Background task tracking

Run with: python3 migrate_jarvis_tables.py
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from app.models.jarvis_inbox import Base as InboxBase
from app.models.daily_brief import Base as BriefBase  
from app.models.jarvis_tasks import Base as TaskBase
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

def run_migration():
    """Run the Jarvis mode table migration"""
    
    logger.info("Starting Jarvis mode migration...")
    
    try:
        # Create engine
        engine = create_engine(DATABASE_URL)
        
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("Database connection successful")
        
        # Create tables from models
        logger.info("Creating jarvis_inbox table...")
        InboxBase.metadata.create_all(bind=engine, tables=[InboxBase.metadata.tables['jarvis_inbox']])
        
        logger.info("Creating daily_briefs table...")
        BriefBase.metadata.create_all(bind=engine, tables=[BriefBase.metadata.tables['daily_briefs']])
        
        logger.info("Creating jarvis_tasks table...")
        TaskBase.metadata.create_all(bind=engine, tables=[TaskBase.metadata.tables['jarvis_tasks']])
        
        # Create indexes
        logger.info("Creating indexes...")
        with engine.connect() as conn:
            # Inbox indexes
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_inbox_user_status 
                ON jarvis_inbox(user_id, status)
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_inbox_created_at 
                ON jarvis_inbox(created_at)
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_inbox_dedupe_key 
                ON jarvis_inbox(dedupe_key) WHERE dedupe_key IS NOT NULL
            """))
            
            # Brief indexes
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_brief_user_date 
                ON daily_briefs(user_id, brief_date)
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_brief_date 
                ON daily_briefs(brief_date)
            """))
            
            # Task indexes
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_tasks_user_state 
                ON jarvis_tasks(user_id, state)
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_tasks_created_at 
                ON jarvis_tasks(created_at)
            """))
            
            conn.commit()
            logger.info("Indexes created successfully")
        
        # Verify tables exist
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('jarvis_inbox', 'daily_briefs', 'jarvis_tasks')
                ORDER BY table_name
            """))
            
            tables = [row[0] for row in result.fetchall()]
            logger.info(f"Created tables: {', '.join(tables)}")
            
            if len(tables) == 3:
                logger.info("✅ All Jarvis tables created successfully!")
                return True
            else:
                logger.error(f"❌ Expected 3 tables, found {len(tables)}: {tables}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        return False


def verify_migration():
    """Verify the migration was successful"""
    
    logger.info("Verifying migration...")
    
    try:
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Check table structures
            for table in ['jarvis_inbox', 'daily_briefs', 'jarvis_tasks']:
                result = conn.execute(text(f"""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns 
                    WHERE table_name = '{table}'
                    ORDER BY ordinal_position
                """))
                
                columns = result.fetchall()
                logger.info(f"Table '{table}' has {len(columns)} columns")
                
                # Check for required columns
                column_names = [col[0] for col in columns]
                
                if table == 'jarvis_inbox':
                    required = ['id', 'user_id', 'kind', 'title', 'status', 'created_at']
                elif table == 'daily_briefs':
                    required = ['id', 'user_id', 'brief_date', 'sections', 'generated_at']
                elif table == 'jarvis_tasks':
                    required = ['id', 'user_id', 'kind', 'title', 'state', 'created_at']
                
                missing = [col for col in required if col not in column_names]
                if missing:
                    logger.error(f"❌ Table '{table}' missing columns: {missing}")
                    return False
            
            # Check indexes
            result = conn.execute(text("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename IN ('jarvis_inbox', 'daily_briefs', 'jarvis_tasks')
                AND indexname LIKE 'idx_%'
                ORDER BY indexname
            """))
            
            indexes = [row[0] for row in result.fetchall()]
            logger.info(f"Created indexes: {', '.join(indexes)}")
            
            expected_indexes = [
                'idx_inbox_user_status', 'idx_inbox_created_at', 'idx_inbox_dedupe_key',
                'idx_brief_user_date', 'idx_brief_date',
                'idx_tasks_user_state', 'idx_tasks_created_at'
            ]
            
            missing_indexes = [idx for idx in expected_indexes if idx not in indexes]
            if missing_indexes:
                logger.warning(f"⚠️ Missing some indexes: {missing_indexes}")
            
            logger.info("✅ Migration verification completed successfully!")
            return True
            
    except Exception as e:
        logger.error(f"❌ Migration verification failed: {e}")
        return False


if __name__ == "__main__":
    logger.info("=== Jarvis Mode Migration ===")
    
    # Run migration
    success = run_migration()
    
    if success:
        # Verify migration
        verify_success = verify_migration()
        
        if verify_success:
            logger.info("🎉 Jarvis mode migration completed successfully!")
            logger.info("Next steps:")
            logger.info("1. Add Jarvis routes to main_simple.py")
            logger.info("2. Update frontend with Jarvis components")
            logger.info("3. Set up cron job for daily briefs")
            logger.info("4. Configure environment variables")
        else:
            logger.error("Migration verification failed")
            sys.exit(1)
    else:
        logger.error("Migration failed")
        sys.exit(1)