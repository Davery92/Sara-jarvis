#!/usr/bin/env python3
"""
Update Solo User Credentials

Updates the solo user with the correct email and password.
"""

import os
import sys
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent / 'backend'
sys.path.insert(0, str(backend_dir))

try:
    from app.db.session import SessionLocal
    from passlib.context import CryptContext
    from sqlalchemy import text
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the jarvis directory with backend dependencies installed")
    sys.exit(1)

def main():
    """Update solo user with correct credentials"""
    
    if not os.getenv('DATABASE_URL'):
        print("❌ DATABASE_URL environment variable not set")
        sys.exit(1)
    
    # Password context for hashing
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    # Correct credentials
    correct_email = "david@avery.cloud"
    correct_password = "Nutman17!"
    password_hash = pwd_context.hash(correct_password)
    
    db = SessionLocal()
    
    try:
        # Check current solo user
        current = db.execute(text("SELECT * FROM app_user WHERE id = '1'")).first()
        
        if current:
            print(f"✅ Found solo user: {current.email} (ID: {current.id})")
            
            # Update email and password
            db.execute(text("""
                UPDATE app_user 
                SET email = :email, password_hash = :hash 
                WHERE id = '1'
            """), {"email": correct_email, "hash": password_hash})
            db.commit()
            
            print(f"✅ Updated solo user credentials")
            print(f"   Old Email: {current.email}")
            print(f"   New Email: {correct_email}")
            print(f"   Password: {correct_password}")
            print("   You can now log in to the dashboard with your credentials!")
            
        else:
            print("❌ Solo user not found")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()