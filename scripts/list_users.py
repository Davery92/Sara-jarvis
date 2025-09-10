#!/usr/bin/env python3
"""
List Users

Shows all users in the database.
"""

import os
import sys
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent / 'backend'
sys.path.insert(0, str(backend_dir))

try:
    from app.db.session import SessionLocal
    from sqlalchemy import text
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

def main():
    """List all users"""
    
    if not os.getenv('DATABASE_URL'):
        print("❌ DATABASE_URL environment variable not set")
        sys.exit(1)
    
    db = SessionLocal()
    
    try:
        # Get all users
        users = db.execute(text("SELECT id, email, created_at FROM app_user ORDER BY created_at")).fetchall()
        
        if users:
            print("✅ Found users:")
            for user in users:
                print(f"   ID: {user.id}")
                print(f"   Email: {user.email}")
                print(f"   Created: {user.created_at}")
                print()
        else:
            print("❌ No users found")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    main()