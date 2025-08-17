#!/usr/bin/env python3
import sqlite3
import os

# Connect to SQLite database
db_path = 'sara_hub.db'
if not os.path.exists(db_path):
    print(f"Database {db_path} doesn't exist")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check if folder_id column exists in note table
    cursor.execute("PRAGMA table_info(note)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'folder_id' not in columns:
        print("Adding folder_id column to note table...")
        cursor.execute("ALTER TABLE note ADD COLUMN folder_id TEXT")
        print("✅ Added folder_id column")
    else:
        print("ℹ️ folder_id column already exists")
    
    # Create folder table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS folder (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            parent_id TEXT,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("✅ Ensured folder table exists")
    
    conn.commit()
    print("✅ Database migration completed successfully")
    
except Exception as e:
    print(f"❌ Error: {e}")
    conn.rollback()
finally:
    conn.close()