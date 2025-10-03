#!/usr/bin/env python3
"""
Test password verification
"""
import os
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, DateTime

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

Base = declarative_base()

class User(Base):
    __tablename__ = "app_user"
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def test_login(email: str, password: str):
    """Test login"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        user = session.query(User).filter(User.email == email).first()
        if not user:
            print(f"❌ User not found: {email}")
            return

        print(f"✓ User found: {email}")
        print(f"  Password hash: {user.password_hash[:60]}...")

        # Try different verification methods
        print("\nTest 1: Direct string verification")
        try:
            result1 = pwd_context.verify(password, user.password_hash)
            print(f"  Result: {result1}")
        except Exception as e:
            print(f"  Error: {e}")

        print("\nTest 2: Bytes verification (current method)")
        try:
            password_bytes = password.encode('utf-8')[:72]
            result2 = pwd_context.verify(password_bytes, user.password_hash)
            print(f"  Result: {result2}")
        except Exception as e:
            print(f"  Error: {e}")

        print("\nTest 3: Hash the password and compare format")
        try:
            # Hash with bytes
            test_hash_bytes = pwd_context.hash(password.encode('utf-8')[:72])
            print(f"  Hash with bytes: {test_hash_bytes[:60]}...")

            # Hash with string
            test_hash_string = pwd_context.hash(password)
            print(f"  Hash with string: {test_hash_string[:60]}...")
        except Exception as e:
            print(f"  Error: {e}")

    finally:
        session.close()

if __name__ == "__main__":
    test_login("david@avery.cloud", "Nutman17!")
