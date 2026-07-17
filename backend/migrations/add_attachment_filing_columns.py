"""
Migration: Add filing columns to email_attachment table

This adds columns to track when Sara files important attachments to Projects:
- filed_to_project_id: The project the file was filed to
- filed_to_folder_id: The folder within the project (Sara's Findings)
- filed_to_file_id: The ProjectFile record created
- filed_at: When the filing occurred
- filing_analysis: Sara's reasoning for why the attachment is important
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
)


def run_migration():
    """Add filing columns to email_attachment table."""
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        # Check if columns already exist
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'email_attachment' AND column_name = 'filed_to_project_id'
        """))

        if result.fetchone():
            print("Migration already applied - filing columns exist")
            return

        print("Adding filing columns to email_attachment table...")

        # Add the new columns
        conn.execute(text("""
            ALTER TABLE email_attachment
            ADD COLUMN IF NOT EXISTS filed_to_project_id VARCHAR,
            ADD COLUMN IF NOT EXISTS filed_to_folder_id VARCHAR,
            ADD COLUMN IF NOT EXISTS filed_to_file_id VARCHAR,
            ADD COLUMN IF NOT EXISTS filed_at TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS filing_analysis TEXT
        """))

        conn.commit()
        print("Migration complete - filing columns added")


if __name__ == "__main__":
    run_migration()
