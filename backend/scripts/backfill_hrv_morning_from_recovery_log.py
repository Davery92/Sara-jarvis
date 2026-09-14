#!/usr/bin/env python3
"""
backfill_hrv_morning_from_recovery_log.py — close the historical HRV gap.

`daily_recovery_log.hrv` has a reading on nearly every day; `health_metric`
(`hrv_morning`) — the store every context/readiness/brief path actually reads —
has one on about a third of them, because the iOS batch sync only emitted
`hrv_morning` when the sync ran 05:00–07:59 local AND a sample existed in the
preceding 4 hours. `health_metric_mirror` fixes that going forward; this fixes
the past.

Each backfilled row is stamped 06:00 ET on the recovery log's date, the same
stamp iOS uses, so a real `hrv_morning` for the same day collides on
`ix_health_metric_dedup` and is a no-op rather than a duplicate.

Run from inside the backend container:
  docker compose exec -T backend python scripts/backfill_hrv_morning_from_recovery_log.py --days 120 [--dry-run]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

# Days present in daily_recovery_log with a usable HRV but no hrv_morning row.
GAP_ROWS = """
    SELECT r.user_id, r.log_date, r.hrv
    FROM daily_recovery_log r
    WHERE r.hrv IS NOT NULL AND r.hrv > 0
      AND r.log_date >= current_date - CAST(:days AS integer)
      AND NOT EXISTS (
        SELECT 1 FROM health_metric h
        WHERE h.user_id = r.user_id
          AND h.metric_type = 'hrv_morning'
          AND (h.recorded_at AT TIME ZONE 'America/New_York')::date = r.log_date)
    ORDER BY r.log_date
"""

INSERT = """
    INSERT INTO health_metric (id, user_id, metric_type, value, recorded_at, source, metadata)
    SELECT gen_random_uuid()::text, r.user_id, 'hrv_morning', r.hrv,
           (r.log_date::timestamp + interval '6 hours') AT TIME ZONE 'America/New_York',
           'apple_health',
           '{"morning_reading": true, "sample_count": 1, "via": "backfill-daily-recovery-log"}'::jsonb
    FROM daily_recovery_log r
    WHERE r.hrv IS NOT NULL AND r.hrv > 0
      AND r.log_date >= current_date - CAST(:days AS integer)
      AND NOT EXISTS (
        SELECT 1 FROM health_metric h
        WHERE h.user_id = r.user_id
          AND h.metric_type = 'hrv_morning'
          AND (h.recorded_at AT TIME ZONE 'America/New_York')::date = r.log_date)
    ON CONFLICT (user_id, metric_type, recorded_at) DO NOTHING
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=120, help="look-back window in days (default 120)")
    ap.add_argument("--dry-run", action="store_true", help="report what would be written, write nothing")
    args = ap.parse_args()

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        gaps = db.execute(text(GAP_ROWS), {"days": args.days}).fetchall()
        if not gaps:
            print(f"No gap days in the last {args.days} days — nothing to backfill.")
            return 0

        print(f"Gap days found in the last {args.days} days: {len(gaps)}")
        print(f"  range: {gaps[0].log_date} … {gaps[-1].log_date}")
        print(f"  HRV min/max: {min(float(g.hrv) for g in gaps):.0f} / {max(float(g.hrv) for g in gaps):.0f}")

        if args.dry_run:
            print("\n--dry-run: no rows written. Sample:")
            for g in gaps[:10]:
                print(f"  {g.log_date}  hrv={g.hrv}  user={g.user_id}")
            if len(gaps) > 10:
                print(f"  … and {len(gaps) - 10} more")
            return 0

        result = db.execute(text(INSERT), {"days": args.days})
        db.commit()
        print(f"\nInserted {result.rowcount} hrv_morning rows.")

        remaining = db.execute(text(GAP_ROWS), {"days": args.days}).fetchall()
        print(f"Remaining gap days: {len(remaining)} (expect 0)")
        return 0 if not remaining else 1
    except Exception as e:
        db.rollback()
        print(f"FAILED ({type(e).__name__}): {e}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
