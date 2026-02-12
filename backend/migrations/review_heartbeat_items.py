"""
Review active heartbeat_items — prints a formatted report for manual review.

Does NOT auto-edit HEARTBEAT.md. David reviews the output and decides what
(if anything) to merge into HEARTBEAT.md as standing rules.

Usage: python -m migrations.review_heartbeat_items
"""

import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sara:sara123@10.185.1.180:5432/sara_hub")


def review():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, item_type, description, check_logic, condition,
                   config, created_at, created_by, source_context,
                   times_checked, times_triggered, is_active, priority
            FROM heartbeat_items
            WHERE is_active = true
            ORDER BY item_type, created_at
        """))
        rows = result.fetchall()

        if not rows:
            print("\n=== No active heartbeat_items found ===")
            print("The table is empty or all items are inactive. Nothing to review.")
            return

        print(f"\n{'='*70}")
        print(f"  ACTIVE HEARTBEAT ITEMS REVIEW — {len(rows)} items")
        print(f"  Generated: {datetime.now().isoformat()}")
        print(f"{'='*70}\n")

        for row in rows:
            print(f"  ID: {row.id}")
            print(f"  Type: {row.item_type}")
            print(f"  Description: {row.description}")
            print(f"  Check Logic: {row.check_logic}")
            if row.condition:
                print(f"  Condition: {row.condition}")
            if row.config:
                print(f"  Config: {row.config}")
            print(f"  Created: {row.created_at} by {row.created_by}")
            if row.source_context:
                print(f"  Source: {row.source_context[:100]}")
            print(f"  Stats: checked {row.times_checked}x, triggered {row.times_triggered}x")
            print(f"  Priority: {row.priority}")
            print(f"  ---")
            print()

        print(f"{'='*70}")
        print("  ACTION NEEDED: Review each item above and decide whether to:")
        print("  1. Add as a rule in HEARTBEAT.md")
        print("  2. Convert to a standing order")
        print("  3. Leave as-is (historical)")
        print("  4. Deactivate (set is_active = false)")
        print(f"{'='*70}")


if __name__ == "__main__":
    review()
