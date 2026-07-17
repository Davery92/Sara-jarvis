"""
Migration: Add role-based permissions table for app users.

Creates:
  - app_user_role(user_id PK/FK, role, timestamps)

Seeds:
  - role='user' for existing users missing a role row
  - role='admin' for users listed in AUTOMATION_ADMIN_EMAILS

Run with:
    python backend/migrations/add_user_roles.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text


def get_engine():
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://sara:sara123@10.185.1.180:5432/sara_hub",
    )
    return create_engine(database_url)


def _parse_admin_emails() -> list[str]:
    raw = (os.getenv("AUTOMATION_ADMIN_EMAILS") or "").strip()
    if not raw:
        return []
    return [email.strip().lower() for email in raw.split(",") if email.strip()]


def run_migration():
    engine = get_engine()
    admin_emails = _parse_admin_emails()

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_user_role (
                user_id VARCHAR PRIMARY KEY REFERENCES app_user(id) ON DELETE CASCADE,
                role VARCHAR(32) NOT NULL DEFAULT 'user',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_app_user_role
                    CHECK (role IN ('user', 'admin', 'owner'))
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_app_user_role_role
            ON app_user_role (role)
        """))

        # Baseline role row for all known users.
        conn.execute(text("""
            INSERT INTO app_user_role (user_id, role)
            SELECT u.id, 'user'
            FROM app_user u
            ON CONFLICT (user_id) DO NOTHING
        """))

        # Promote configured allowlist users to admin.
        promoted = 0
        for email in admin_emails:
            result = conn.execute(text("""
                INSERT INTO app_user_role (user_id, role)
                SELECT id, 'admin'
                FROM app_user
                WHERE lower(email) = :email
                ON CONFLICT (user_id)
                DO UPDATE SET
                    role = 'admin',
                    updated_at = NOW()
            """), {"email": email})
            promoted += result.rowcount or 0

        conn.commit()

        print("[OK] app_user_role table ready")
        print("[OK] baseline user roles seeded")
        if admin_emails:
            print(f"[OK] promoted admin roles from AUTOMATION_ADMIN_EMAILS: {promoted} row(s)")
        else:
            print("[INFO] AUTOMATION_ADMIN_EMAILS not set; no admin promotions applied")
        print("[DONE] user role migration complete")


if __name__ == "__main__":
    run_migration()

