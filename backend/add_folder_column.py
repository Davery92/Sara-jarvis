#!/usr/bin/env python3
import sys
import os
sys.path.append('/home/david/jarvis/backend')

from sqlalchemy import create_engine
from app.db.base import Base

# Database connection
DATABASE_URL = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
engine = create_engine(DATABASE_URL)

# Create all tables
try:
    Base.metadata.create_all(bind=engine)
    print("✅ All database tables created successfully")
        
except Exception as e:
    print(f"❌ Error: {e}")