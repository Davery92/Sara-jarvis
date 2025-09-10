#!/usr/bin/env python3
"""
Fix Solo User Email

Updates the solo user email to a valid format that passes email validation.
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
    print("Make sure you're running this from the jarvis directory with backend dependencies installed")
    sys.exit(1)

def main():
    """Update solo user email to a valid format"""
    
    if not os.getenv('DATABASE_URL'):
        print("❌ DATABASE_URL environment variable not set")
        sys.exit(1)
    
    # Valid email for solo mode
    new_email = "solo@example.com"
    
    db = SessionLocal()
    
    try:
        # Check current solo user
        current = db.execute(text("SELECT * FROM app_user WHERE id = '1'")).first()
        
        if current:
            print(f"✅ Found solo user: {current.email} (ID: {current.id})")
            
            # Update email
            db.execute(text("UPDATE app_user SET email = :email WHERE id = '1'"), 
                      {"email": new_email})
            db.commit()
            
            print(f"✅ Updated solo user email")
            print(f"   Old Email: {current.email}")
            print(f"   New Email: {new_email}")
            print("   Password: jarvis123")
            print("   You can now log in to the dashboard!")
            
        else:
            print("❌ Solo user not found")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()