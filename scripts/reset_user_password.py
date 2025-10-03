#!/usr/bin/env python3
"""
Reset user password with proper bcrypt bytes handling
"""
import sys
import os
from passlib.context import CryptContext
from sqlalchemy import create_engine, Column, String, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

Base = declarative_base()

class User(Base):
    __tablename__ = "app_user"
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def reset_password(email: str, new_password: str):
    """Reset password for a user"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Find user
        user = session.query(User).filter(User.email == email).first()
        if not user:
            print(f"❌ User with email '{email}' not found")
            return False

        # Hash password - passlib expects string, handles truncation internally
        hashed = pwd_context.hash(new_password)

        # Update user
        user.password_hash = hashed
        session.commit()

        print(f"✅ Password reset successfully for {email}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        session.rollback()
        return False
    finally:
        session.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python reset_user_password.py <email> <new_password>")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    reset_password(email, password)
