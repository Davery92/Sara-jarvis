"""Add proxmox_container table for ACS dynamic container provisioning."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from app.core.config import settings


def upgrade():
    engine = create_engine(settings.database_url.replace('+asyncpg', ''))
    with engine.begin() as conn:
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'proxmox_container')"
        ))
        if result.scalar():
            print("proxmox_container already exists, skipping.")
            return

        conn.execute(text("""
            CREATE TABLE proxmox_container (
                id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                vmid INTEGER NOT NULL UNIQUE,
                user_id VARCHAR NOT NULL,
                session_id VARCHAR,
                hostname VARCHAR(100) NOT NULL,
                ip_address VARCHAR(45),
                preset VARCHAR(30) NOT NULL,
                cores INTEGER NOT NULL,
                memory_mb INTEGER NOT NULL,
                disk_gb INTEGER NOT NULL,
                persistent BOOLEAN DEFAULT FALSE,
                purpose TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'creating',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                destroyed_at TIMESTAMPTZ,
                last_used_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text("CREATE INDEX ix_proxmox_container_vmid ON proxmox_container (vmid)"))
        conn.execute(text("CREATE INDEX ix_proxmox_container_user ON proxmox_container (user_id)"))
        conn.execute(text("CREATE INDEX ix_proxmox_container_session ON proxmox_container (session_id)"))
        conn.execute(text("CREATE INDEX ix_proxmox_container_status ON proxmox_container (status)"))
        print("Created 'proxmox_container' table.")


if __name__ == "__main__":
    upgrade()
