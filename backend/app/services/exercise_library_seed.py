"""Exercise library seeding — SARA_UNLEASHED Phase U.7.

R28: workout_log.exercise_id holds free-text movement/exercise names
("Flat DB Bench", "Vertical Pull" — a pattern, not an exercise) with no
canonical entity behind them, and exercise_library sits empty. This seeds
one exercise_library row per distinct name already logged, classifying a
movement_pattern and equipment by keyword — good enough to group variants
for the history API (U.7 layer 2), not a claim of perfect taxonomy. Compound
"X or Y" names (the plan's own example: "Back Squat (Barbell / Hack Squat
or Leg Press)") get every matching equipment tag joined with '/' rather than
an arbitrary single guess.
"""

import logging
import re
import uuid
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MOVEMENT_RULES: List[Tuple[str, str]] = [
    (r"\bsquat\b|leg press", "squat"),
    (r"deadlift|hip hinge|kettlebell swing", "hinge"),
    (r"incline.*press|incline.*bench", "incline_press"),
    (r"overhead press|shoulder press", "vertical_press"),
    # Lateral raise / rear delt must precede the generic "fly" catch below —
    # "Rear Delt Fly" was matching the horizontal_press rule's bare "fly"
    # keyword first, dumping a rear-delt isolation move in with flat bench
    # press variants. This is exactly the bug that made the Flat Bench
    # picker show flyes and rear delt alongside real press variants.
    (r"lateral raise|lat raise|rear delt", "shoulder_isolation"),
    # Flies are their own movement — a fundamentally different motion
    # (horizontal adduction, isolation) from a press (a push), even though
    # both hit the chest. Keeping them separate is what makes "what did I
    # do last time on flat bench" show ONLY flat-bench press variants.
    (r"chest fly|pec dec|\bfly\b|\bflyes\b|\bflies\b", "chest_fly"),
    (r"bench|chest press", "horizontal_press"),
    (r"pulldown|pull-?up|vertical pull|pullover", "vertical_pull"),
    (r"\brow\b", "horizontal_pull"),
    (r"leg curl|let curl", "leg_isolation"),
    (r"leg extension", "leg_isolation"),
    (r"\bcurl\b", "arm_isolation"),
    (r"pushdown|skull crusher|triceps", "arm_isolation"),
    (r"shrug", "trap_isolation"),
    (r"crunch|\bab\b", "core"),
]

_EQUIPMENT_RULES: List[Tuple[str, str]] = [
    (r"\bdb\b|dumbbell", "dumbbell"),
    (r"barbell", "barbell"),
    (r"kettlebell", "kettlebell"),
    (r"cable", "cable"),
    (r"\biso\b|iso-|iso ", "machine"),
    (r"machine|plate", "machine"),
    (r"pull-?up", "bodyweight"),
]


def classify(name: str) -> Tuple[str, str]:
    """Return (movement_pattern, equipment) for a free-text exercise name."""
    lowered = name.lower()

    movement = "other"
    for pattern, tag in _MOVEMENT_RULES:
        if re.search(pattern, lowered):
            movement = tag
            break

    equipment_tags: List[str] = []
    for pattern, tag in _EQUIPMENT_RULES:
        if re.search(pattern, lowered) and tag not in equipment_tags:
            equipment_tags.append(tag)
    equipment = "/".join(equipment_tags) if equipment_tags else "other"

    return movement, equipment


async def reclassify_all() -> Dict[str, int]:
    """Recompute movement_pattern/equipment for every existing exercise_library
    row against the current classify() rules. Needed because seed_from_workout_log
    skips rows that already exist by name — a classifier rule fix (like the
    "fly" keyword swallowing rear-delt/lateral-raise moves) would otherwise
    never reach already-seeded rows."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    factory = get_async_session_factory()
    changed = 0
    async with factory() as db:
        rows = (await db.execute(text("SELECT id, name, movement_pattern FROM exercise_library"))).fetchall()
        for ex_id, name, old_movement in rows:
            new_movement, new_equipment = classify(name)
            if new_movement != old_movement:
                await db.execute(text("""
                    UPDATE exercise_library
                    SET movement_pattern = :movement, equipment_required = CAST(:equipment AS json), updated_at = NOW()
                    WHERE id = :id
                """), {"id": ex_id, "movement": new_movement, "equipment": f'["{new_equipment}"]'})
                changed += 1
        await db.commit()
    logger.info(f"exercise_library reclassify: changed={changed}/{len(rows)}")
    return {"changed": changed, "total": len(rows)}


async def seed_from_workout_log(user_id: str) -> Dict[str, int]:
    """Create one exercise_library row per distinct workout_log.exercise_id
    not already represented (matched by exact, case-insensitive name).
    Idempotent — safe to re-run as new exercise names appear in logs."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    factory = get_async_session_factory()
    created = 0
    skipped = 0
    async with factory() as db:
        rows = (await db.execute(text("""
            SELECT DISTINCT exercise_id FROM workout_log
            WHERE user_id = :uid AND exercise_id IS NOT NULL AND exercise_id != ''
        """), {"uid": user_id})).fetchall()

        existing = {
            r[0].lower() for r in (await db.execute(
                text("SELECT name FROM exercise_library")
            )).fetchall()
        }

        for (name,) in rows:
            name = name.strip()
            if not name or name.lower() in existing:
                skipped += 1
                continue
            movement, equipment = classify(name)
            await db.execute(text("""
                INSERT INTO exercise_library
                (id, name, movement_pattern, equipment_required, created_at, updated_at)
                VALUES (:id, :name, :movement, CAST(:equipment AS json), NOW(), NOW())
            """), {
                "id": str(uuid.uuid4()),
                "name": name,
                "movement": movement,
                "equipment": f'["{equipment}"]',
            })
            existing.add(name.lower())
            created += 1

        await db.commit()

    logger.info(f"exercise_library seed: created={created} skipped(existing)={skipped}")
    return {"created": created, "skipped": skipped}
