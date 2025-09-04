#!/usr/bin/env python3

"""
Migration script to add the note_connection table for knowledge garden features.
"""

import os
import sys
from sqlalchemy import create_engine, text, Column, String, Integer, DateTime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
import uuid

# Add the app directory to the path so we can import models
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.db.base import Base
from app.models import NoteConnection

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

def main():
    print("🔄 Adding note_connection table...")
    
    try:
        # Create engine
        engine = create_engine(DATABASE_URL, echo=True)
        
        # Create a session
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Check if table already exists
        result = session.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'note_connection'
            );
        """))
        
        table_exists = result.scalar()
        
        if table_exists:
            print("✅ note_connection table already exists. Skipping creation.")
        else:
            print("📝 Creating note_connection table...")
            
            # Create the table
            NoteConnection.__table__.create(engine, checkfirst=True)
            
            print("✅ note_connection table created successfully!")
        
        # Check table structure
        result = session.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'note_connection'
            ORDER BY ordinal_position;
        """))
        
        columns = result.fetchall()
        print("\n📋 Table structure:")
        for col in columns:
            print(f"  - {col[0]}: {col[1]} ({'NULL' if col[2] == 'YES' else 'NOT NULL'})")
        
        session.close()
        print("\n🎉 Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()