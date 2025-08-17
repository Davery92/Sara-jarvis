#!/usr/bin/env python3
import sqlite3
import psycopg
import uuid

# Connect to SQLite (source)
sqlite_conn = sqlite3.connect('sara_hub.db')
sqlite_cur = sqlite_conn.cursor()

# Connect to PostgreSQL (destination)
pg_conn = psycopg.connect('postgresql://sara:sara123@10.185.1.180:5432/sara_hub')
pg_cur = pg_conn.cursor()

try:
    # Get users from SQLite
    sqlite_cur.execute('SELECT id, email, password_hash FROM app_user')
    users = sqlite_cur.fetchall()
    
    print(f"Found {len(users)} users in SQLite database")
    
    for user in users:
        user_id, email, password_hash = user
        print(f"Migrating user: {email}")
        
        # Insert into PostgreSQL
        pg_cur.execute(
            "INSERT INTO app_user (id, email, password_hash) VALUES (%s, %s, %s) ON CONFLICT (email) DO NOTHING",
            (user_id, email, password_hash)
        )
    
    # Get notes from SQLite  
    sqlite_cur.execute('SELECT id, user_id, title, content, created_at, updated_at, folder_id FROM note')
    notes = sqlite_cur.fetchall()
    
    print(f"Found {len(notes)} notes in SQLite database")
    
    for note in notes:
        note_id, user_id, title, content, created_at, updated_at, folder_id = note
        print(f"Migrating note: {title or 'Untitled'}")
        
        # Insert into PostgreSQL
        pg_cur.execute(
            "INSERT INTO note (id, user_id, title, content, created_at, updated_at, folder_id) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (note_id, user_id, title, content, created_at, updated_at, folder_id)
        )
    
    pg_conn.commit()
    print("✅ Migration completed successfully")
    
except Exception as e:
    print(f"❌ Error during migration: {e}")
    pg_conn.rollback()
finally:
    sqlite_conn.close()
    pg_conn.close()