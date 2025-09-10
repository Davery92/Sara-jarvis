#!/usr/bin/env python3
"""
Setup script to create the solo user for Jarvis mode
"""

import os
import sys
from datetime import datetime
import uuid

# Add the backend directory to the path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
sys.path.insert(0, backend_dir)

try:
    from app.db.session import SessionLocal
    from sqlalchemy import text
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

def setup_solo_user():
    """Create the solo user for Jarvis mode"""
    
    db = SessionLocal()
    
    try:
        # Check if user with ID "1" exists
        result = db.execute(text("SELECT id, email FROM app_user WHERE id = '1'")).fetchone()
        
        if result:
            print(f"✅ Solo user already exists: {result.email} (ID: {result.id})")
        else:
            print("Creating solo user...")
            
            # Create the solo user
            db.execute(text("""
                INSERT INTO app_user (id, email, password_hash, created_at)
                VALUES ('1', 'owner@jarvis.local', 'dummy-hash-not-used-in-solo-mode', NOW())
            """))
            
            db.commit()
            print("✅ Created solo user: owner@jarvis.local (ID: 1)")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

def check_tables():
    """Check that our Jarvis tables exist"""
    
    db = SessionLocal()
    
    try:
        # Check jarvis_inbox
        result = db.execute(text("""
            SELECT count(*) as count FROM information_schema.tables 
            WHERE table_name IN ('jarvis_inbox', 'daily_briefs', 'jarvis_tasks')
        """)).fetchone()
        
        print(f"📊 Jarvis tables found: {result.count}/3")
        
        if result.count == 3:
            print("✅ All Jarvis tables exist")
        else:
            print("⚠️ Some Jarvis tables are missing. Run migration script.")
            
    except Exception as e:
        print(f"❌ Error checking tables: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("=== Jarvis Solo Mode Setup ===")
    check_tables()
    setup_solo_user()
    print("=== Setup Complete ===")