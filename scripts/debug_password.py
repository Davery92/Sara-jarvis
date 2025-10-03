#!/usr/bin/env python3
"""
Debug password hashing and verification
"""
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

password = "Nutman17!"

print(f"Original password: '{password}'")
print(f"Password length: {len(password)}")
print(f"Password repr: {repr(password)}")

# Create a hash
hash1 = pwd_context.hash(password)
print(f"\nCreated hash: {hash1}")

# Verify immediately
result = pwd_context.verify(password, hash1)
print(f"Immediate verification: {result}")

# Try with different password
wrong = "wrongpassword"
result2 = pwd_context.verify(wrong, hash1)
print(f"Wrong password verification: {result2}")
