#!/usr/bin/env python3
"""
Fix user_profile table columns to match the model
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
    """Fix user_profile table column types"""
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # Check current schema
            logger.info("🔍 Checking current user_profile schema...")
            result = conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'user_profile' 
                ORDER BY ordinal_position;
            """))
            
            logger.info("📋 Current user_profile columns:")
            for row in result:
                logger.info(f"  {row.column_name}: {row.data_type}")
            
            # Fix autonomy_level column type
            logger.info("🔧 Fixing autonomy_level column type...")
            conn.execute(text("""
                ALTER TABLE user_profile 
                ALTER COLUMN autonomy_level TYPE VARCHAR(20);
            """))
            
            # Fix communication_style if needed
            logger.info("🔧 Ensuring communication_style is VARCHAR(20)...")
            conn.execute(text("""
                ALTER TABLE user_profile 
                ALTER COLUMN communication_style TYPE VARCHAR(20);
            """))
            
            conn.commit()
            logger.info("✅ Successfully fixed user_profile column types")
            
            # Verify the fixes
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
        logger.error(f"❌ Failed to fix table: {e}")
        return False
        
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)