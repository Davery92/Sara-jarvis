#!/usr/bin/env python3
"""
Create only the missing GTKY tables
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
    """Create only missing GTKY tables"""
    engine = create_engine(DATABASE_URL)
    
    # Only create missing tables
    table_creations = [
        # GTKY Session table
        """
        CREATE TABLE IF NOT EXISTS gtky_session (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR REFERENCES app_user(id) ON DELETE CASCADE,
            pack_id VARCHAR NOT NULL,
            pack_name VARCHAR NOT NULL,
            current_question INTEGER DEFAULT 0,
            responses JSONB DEFAULT '[]'::jsonb,
            status VARCHAR DEFAULT 'active',
            personality_mode VARCHAR DEFAULT 'companion',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            completed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL
        );
        """,
        
        # Daily Reflection table  
        """
        CREATE TABLE IF NOT EXISTS daily_reflection (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR REFERENCES app_user(id) ON DELETE CASCADE,
            reflection_date DATE NOT NULL,
            responses JSONB DEFAULT '{}'::jsonb,
            insights JSONB DEFAULT '[]'::jsonb,
            mood_score INTEGER DEFAULT NULL,
            energy_level INTEGER DEFAULT NULL,
            stress_level INTEGER DEFAULT NULL,
            gratitude_items JSONB DEFAULT '[]'::jsonb,
            challenges TEXT DEFAULT NULL,
            achievements TEXT DEFAULT NULL,
            tomorrow_goals TEXT DEFAULT NULL,
            ai_insights TEXT DEFAULT NULL,
            status VARCHAR DEFAULT 'draft',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            completed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL
        );
        """
    ]
    
    # Create indexes for new tables only
    index_creations = [
        "CREATE INDEX IF NOT EXISTS idx_gtky_session_user_id ON gtky_session(user_id);",
        "CREATE INDEX IF NOT EXISTS idx_gtky_session_status ON gtky_session(status);", 
        "CREATE INDEX IF NOT EXISTS idx_daily_reflection_user_date ON daily_reflection(user_id, reflection_date);",
        "CREATE INDEX IF NOT EXISTS idx_daily_reflection_date ON daily_reflection(reflection_date);"
    ]
    
    try:
        with engine.connect() as conn:
            logger.info("🔧 Creating missing GTKY tables...")
            
            for sql in table_creations:
                logger.info(f"  Creating table...")
                conn.execute(text(sql))
                
            logger.info("📊 Creating indexes...")
            for sql in index_creations:
                logger.info(f"  Creating index...")  
                conn.execute(text(sql))
                
            conn.commit()
            logger.info("✅ Successfully created missing GTKY tables")
            
            # Verify tables were created
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('gtky_session', 'daily_reflection')
                ORDER BY table_name;
            """))
            
            logger.info("📋 Created tables:")
            for row in result:
                logger.info(f"  ✓ {row.table_name}")
                
    except Exception as e:
        logger.error(f"❌ Failed to create tables: {e}")
        return False
        
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)