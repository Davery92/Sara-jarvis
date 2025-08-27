#!/usr/bin/env python3
"""
Migration script to add GTKY (Get-to-Know-You) related tables
"""

import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

def main():
    print("🔄 Creating GTKY system tables...")
    
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # First, check the actual type of app_user.id
            result = conn.execute(text("""
                SELECT data_type 
                FROM information_schema.columns 
                WHERE table_name = 'app_user' 
                AND column_name = 'id'
            """))
            
            id_type = result.fetchone()
            if id_type:
                print(f"📋 app_user.id type: {id_type[0]}")
                # Use the actual ID type for foreign keys
                user_id_type = "UUID" if "uuid" in id_type[0].lower() else "VARCHAR"
            else:
                print("⚠️  app_user table not found, using UUID")
                user_id_type = "UUID"
            
            # Create user_profile table
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS user_profile (
                user_id {user_id_type} PRIMARY KEY REFERENCES app_user(id),
                profile_data JSONB NOT NULL DEFAULT '{{}}',
                autonomy_level VARCHAR(20) DEFAULT 'moderate',
                communication_style VARCHAR(20) DEFAULT 'balanced',
                notification_channels JSONB DEFAULT '{{}}',
                gtky_completed_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """))
            conn.commit()
            print("✅ Created user_profile table")
            
            # Create gtky_sessions table  
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS gtky_sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id {user_id_type} NOT NULL REFERENCES app_user(id),
                question_pack VARCHAR(50) NOT NULL,
                responses JSONB NOT NULL DEFAULT '{{}}',
                completed_at TIMESTAMP WITH TIME ZONE,
                session_metadata JSONB DEFAULT '{{}}',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """))
            conn.commit()
            print("✅ Created gtky_sessions table")
            
            # Create daily_reflections table
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS daily_reflections (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id {user_id_type} NOT NULL REFERENCES app_user(id),
                reflection_date DATE NOT NULL,
                responses JSONB NOT NULL DEFAULT '{{}}',
                insights_generated JSONB DEFAULT '{{}}',
                mood_score INTEGER,
                reflection_duration_minutes INTEGER,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """))
            conn.commit()
            print("✅ Created daily_reflections table")
            
            # Create reflection_settings table
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS reflection_settings (
                user_id {user_id_type} PRIMARY KEY REFERENCES app_user(id),
                preferred_time TIME DEFAULT '21:00',
                timezone VARCHAR(50) DEFAULT 'UTC',
                enabled BOOLEAN DEFAULT TRUE,
                quiet_hours JSONB DEFAULT '{{}}',
                reminder_channels JSONB DEFAULT '{{}}',
                streak_count INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """))
            conn.commit()
            print("✅ Created reflection_settings table")
            
            # Create privacy_settings table
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS privacy_settings (
                user_id {user_id_type} PRIMARY KEY REFERENCES app_user(id),
                memory_retention_days INTEGER DEFAULT 365,
                share_reflections_with_ai BOOLEAN DEFAULT TRUE,
                autonomous_level VARCHAR(20) DEFAULT 'auto',
                data_categories JSONB DEFAULT '{{}}',
                export_enabled BOOLEAN DEFAULT TRUE,
                analytics_enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """))
            conn.commit()
            print("✅ Created privacy_settings table")
            
            # Create user_activity_log table
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS user_activity_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id {user_id_type} NOT NULL REFERENCES app_user(id),
                action_type VARCHAR(50) NOT NULL,
                action_description TEXT,
                data_accessed JSONB DEFAULT '{{}}',
                ai_insights_generated JSONB DEFAULT '{{}}',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """))
            conn.commit()
            print("✅ Created user_activity_log table")
        
        print("\n🎉 All GTKY system tables created successfully!")
        print("📋 Tables created:")
        print("   - user_profile: Stores user profile data from GTKY interview")
        print("   - gtky_sessions: Tracks interview sessions and responses")
        print("   - daily_reflections: Stores nightly reflection entries")
        print("   - reflection_settings: User preferences for reflection routine")
        print("   - privacy_settings: Privacy and control settings")
        print("   - user_activity_log: Audit log for transparency")
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        raise

if __name__ == "__main__":
    main()