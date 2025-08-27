#!/usr/bin/env python3
"""
Fix gtky_sessions table to use VARCHAR instead of UUID columns
"""

import sys
sys.path.insert(0, '/home/david/jarvis/backend')

from sqlalchemy import create_engine, text
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"

def main():
    """Drop and recreate gtky_sessions table with correct VARCHAR columns"""
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            logger.info("🗑️ Dropping old gtky_sessions table...")
            conn.execute(text("DROP TABLE IF EXISTS gtky_sessions CASCADE;"))
            
            logger.info("🔧 Creating gtky_sessions table with VARCHAR columns...")
            conn.execute(text("""
                CREATE TABLE gtky_sessions (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR REFERENCES app_user(id) ON DELETE CASCADE,
                    question_pack VARCHAR(50) NOT NULL,
                    responses JSONB DEFAULT '{}'::jsonb NOT NULL,
                    completed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
                    session_metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """))
            
            logger.info("📊 Creating indexes...")
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gtky_sessions_user_id ON gtky_sessions(user_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gtky_sessions_pack ON gtky_sessions(question_pack);"))
            
            conn.commit()
            logger.info("✅ Successfully fixed gtky_sessions table")
            
            # Verify the table structure
            result = conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'gtky_sessions' 
                ORDER BY ordinal_position;
            """))
            
            logger.info("📋 Updated gtky_sessions columns:")
            for row in result:
                logger.info(f"  {row.column_name}: {row.data_type}")
                
    except Exception as e:
        logger.error(f"❌ Failed to fix table: {e}")
        return False
        
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)