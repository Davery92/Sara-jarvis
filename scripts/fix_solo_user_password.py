#!/usr/bin/env python3
"""
Fix Solo User Password

Updates the solo user with a proper password hash for authentication.
"""

import os
import sys
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent / 'backend'
sys.path.insert(0, str(backend_dir))

try:
    from app.db.session import SessionLocal
    from app.models.user import User
    from passlib.context import CryptContext
    from sqlalchemy import text
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the jarvis directory with backend dependencies installed")
    sys.exit(1)

def main():
    """Update solo user with proper password"""
    
    if not os.getenv('DATABASE_URL'):
        print("❌ DATABASE_URL environment variable not set")
        sys.exit(1)
    
    # Password context for hashing
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    # Default password for solo mode
    solo_password = "jarvis123"  # Change this if needed
    password_hash = pwd_context.hash(solo_password)
    
    db = SessionLocal()
    
    try:
        # Check if solo user exists - try both string and UUID formats
        user = None
        try:
            # Try with string ID first (if inserted as string)
            user = db.execute(text("SELECT * FROM app_user WHERE id = '1'")).first()
        except:
            pass
        
        if not user:
            # Try with UUID format
            user = db.query(User).filter(User.id == '1').first()
        
        if user:
            print(f"✅ Found solo user: {user.email} (ID: {user.id})")
            
            # Update password hash using raw SQL since ORM has type issues
            db.execute(text("UPDATE app_user SET password_hash = :hash WHERE id = '1'"), 
                      {"hash": password_hash})
            db.commit()
            
            print(f"✅ Updated solo user password")
            print(f"   Email: {user.email}")
            print(f"   Password: {solo_password}")
            print("   You can now log in to the dashboard!")
            
        else:
            print("❌ Solo user not found")
            print("Run setup_solo_user.py first")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()