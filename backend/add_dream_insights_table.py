#!/usr/bin/env python3
"""
Migration script to create dream_insight table.
This table stores AI-generated insights from Sara's nightly dreaming process.
"""
import sys
import os
sys.path.append('/home/david/jarvis/backend')

from sqlalchemy import create_engine
from app.main_simple import Base, DreamInsight

# Database connection
DATABASE_URL = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
engine = create_engine(DATABASE_URL)

# Create dream_insight table
try:
    Base.metadata.create_all(bind=engine)
    print("✅ Dream insights table created successfully!")
    print("   Table: dream_insight")
    print("   Columns: id, user_id, dream_date, insight_type, confidence,")
    print("            title, content, related_episodes, surfaced_at,")
    print("            user_feedback, created_at")

except Exception as e:
    print(f"❌ Error creating table: {e}")
