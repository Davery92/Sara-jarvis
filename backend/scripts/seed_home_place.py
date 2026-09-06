#!/usr/bin/env python3
"""
seed_home_place.py — ensure an active place_type='home' known_place row
exists (docs/SARA_AMNESIA_FIX_PLAN_2026_09_06.md Phase 2 §1).

Everything downstream of the home anchor — distance_from_home_km,
away_since, away_mode() — silently no-ops without this row, the way "away
from home" was underivable for the whole Salem trip because no known_place
had place_type='home' at all.

Idempotent: if an active home row already exists, this only reports it and
exits 0. Coordinates come from --lat/--lon (get them from Home Assistant's
zone.home, or David's phone) or from an existing 'Home'-named place row if
one is present but not yet marked place_type='home'/status='active'.

Run from inside the backend container:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python scripts/seed_home_place.py [--lat 40.575 --lon -75.459] [--radius-m 150]
"""
import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--radius-m", type=int, default=150)
    args = parser.parse_args()

    from sqlalchemy import create_engine, text
    from app.core.config import settings

    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        existing = conn.execute(text("""
            SELECT id, name, latitude, longitude FROM known_place
            WHERE user_id = :uid AND place_type = 'home' AND status = 'active'
            LIMIT 1
        """), {"uid": args.user_id}).fetchone()
        if existing:
            print(f"✅ Home already anchored: '{existing.name}' "
                  f"({existing.latitude}, {existing.longitude}), id={existing.id}")
            return 0

        # No active home row — try promoting an existing 'Home'-named place
        # before creating a new one, so we don't fragment visit history.
        named_home = conn.execute(text("""
            SELECT id FROM known_place WHERE user_id = :uid AND lower(name) = 'home'
            ORDER BY visit_count DESC LIMIT 1
        """), {"uid": args.user_id}).fetchone()
        if named_home:
            conn.execute(text("""
                UPDATE known_place SET place_type = 'home', status = 'active', is_active = TRUE
                WHERE id = :id
            """), {"id": named_home.id})
            print(f"✅ Promoted existing 'Home' place ({named_home.id}) to place_type='home', status='active'")
            return 0

        if args.lat is None or args.lon is None:
            print("❌ No home row found and no --lat/--lon given — cannot seed a new one.", file=sys.stderr)
            return 1

        conn.execute(text("""
            INSERT INTO known_place (id, user_id, name, place_type, latitude, longitude,
                                      radius_m, source, visit_count, is_active, status, created_at)
            VALUES (:id, :uid, 'Home', 'home', :lat, :lon, :radius_m, 'seed_script', 0, TRUE, 'active', NOW())
        """), {
            "id": str(uuid.uuid4()), "uid": args.user_id,
            "lat": args.lat, "lon": args.lon, "radius_m": args.radius_m,
        })
        print(f"✅ Seeded new home place at ({args.lat}, {args.lon}), radius {args.radius_m}m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
