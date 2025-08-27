#!/usr/bin/env python3
"""
Add missing GTKY profile columns to user_profile table
"""

import sys
sys.path.insert(0, '/home/david/jarvis/backend')

from sqlalchemy import create_engine, text, MetaData, Table
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"

def main():
    """Add missing profile columns to user_profile table"""
    engine = create_engine(DATABASE_URL)
    
    # SQL statements to add missing columns
    column_additions = [
        "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS profile_data JSONB DEFAULT '{}'::jsonb;",
        "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS communication_style TEXT DEFAULT 'friendly';",
        "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS notification_channels JSONB DEFAULT '[]'::jsonb;", 
        "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS gtky_completed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL;",
    ]
    
    try:
        with engine.connect() as conn:
            logger.info("🔧 Adding missing GTKY profile columns...")
            
            for sql in column_additions:
                logger.info(f"  Executing: {sql}")
                conn.execute(text(sql))
                
            conn.commit()
            logger.info("✅ Successfully added GTKY profile columns")
            
            # Verify the columns were added
            result = conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'user_profile' 
                ORDER BY ordinal_position;
            """))
            
            logger.info("📋 Updated user_profile columns:")
            for row in result:
                logger.info(f"  {row.column_name}: {row.data_type}")
                
    except Exception as e:
        logger.error(f"❌ Failed to add columns: {e}")
        return False
        
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)