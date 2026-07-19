"""One-off: populate calendar ownership config + backfill owner columns (Phase 3).

- Persists the ownership config (family members, aliases, calendar_owners) to
  app_settings so the system stops running on hardcoded DEFAULT_CONFIG.
- Re-classifies every calendar_event row and stores owner / owner_relation.

"Calendar" and "Birthdays" are intentionally left unmapped (per David) so they
resolve to `unknown` and the interoception digest asks about them once.

Run:  docker compose -f docker-compose.dev.yml exec -T backend python scripts/backfill_calendar_owner.py
"""
import asyncio

CONFIG = {
    "self_name": "David",
    "family_members": {"Amanda": "partner", "Everett": "son"},
    "aliases": {"Shitballz": "Amanda", "Ev": "Everett"},
    "calendar_owners": {
        "everett": "Everett",
        "school": "Everett",
        "work": "self",
        "pay day": "self",
        "doggos": "family",
        "family": "family",
        "family calendar": "family",
        "fun!": "per_event",
        "doctors appts": "per_event",
        # "calendar" and "birthdays" deliberately unmapped -> unknown
    },
    # David chose to leave these unmapped — don't nag him about them.
    "acknowledged_unmapped": ["calendar", "birthdays"],
}


async def _backfill():
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.services.calendar_ownership import classify_event, get_config
    cfg = get_config(force_reload=True)
    factory = get_async_session_factory()
    counts = {}
    async with factory() as db:
        rows = (await db.execute(text(
            "SELECT id, title, ios_calendar_name, source FROM calendar_event"))).mappings().all()
        for r in rows:
            own = classify_event(r["title"], r["ios_calendar_name"], config=cfg, source=r["source"])
            await db.execute(text(
                "UPDATE calendar_event SET owner = :o, owner_relation = :rel WHERE id = :id"),
                {"o": own.owner, "rel": own.relation, "id": r["id"]})
            counts[own.owner] = counts.get(own.owner, 0) + 1
        await db.commit()
    return counts


def main():
    from app.services.calendar_ownership import save_config
    save_config(CONFIG)
    print("Saved calendar_ownership config to app_settings.")
    counts = asyncio.run(_backfill())
    print("Backfilled owner for calendar_event rows:")
    for owner, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {owner}: {n}")


if __name__ == "__main__":
    main()
