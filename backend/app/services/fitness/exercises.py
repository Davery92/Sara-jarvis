"""Canonical exercise identity: resolution, aliases, scope, backfill.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 12.

What identity is for here: PR history and progression comparison. If
"Barbell Bench" and "BB Bench" are two lifts, neither has a complete record;
if "Bench Press" and "Smith Machine Bench Press" are one lift, the record
belongs to whichever was easier. Both failures are silent and both corrupt
the thing the athlete cares most about.

So the rules, in the order they matter:

1. **Resolution is exact, on a normalized string.** `normalize_code` is the
   same function measurement codes use. "BB  Bench-Press" and
   "bb bench press" normalize identically; nothing else matches.
2. **Ambiguity returns candidates, never a choice.** Two reviewed aliases
   for one normalized string is a real ambiguity. "Bench" with a barbell and
   a dumbbell variant both present is a question, not a default.
3. **A fuzzy match is a suggestion and is never persisted as a resolution.**
   `suggest()` exists for a human to pick from; `resolve()` will not use it.
   An `inferred` alias row is excluded from the lookup index by construction.
4. **Variants keep separate histories.** Barbell and dumbbell bench may
   share a `parent_exercise_id` so "how much horizontal pressing" is
   answerable, and they never share a PR.
5. **Backfill is dry-run first and only writes unambiguous matches.** An
   unresolved legacy name stays unresolved and is reported, because guessing
   would attribute one athlete's sets to a movement they never did.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import normalize_code
from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

# Load conventions. Each says how to read the number in a load column, and
# they are not interchangeable: 40 per hand is 80 on the bar, 40 of pull-up
# assistance makes the lift *easier*, and a machine's stack numbers are not
# kilograms of anything comparable to a barbell.
LOAD_TOTAL = "total"
LOAD_PER_HAND = "per_hand"
LOAD_ASSISTED = "assisted"
LOAD_BODYWEIGHT = "bodyweight"
LOAD_STACK = "stack"

VALID_LOAD_CONVENTIONS = frozenset({
    LOAD_TOTAL, LOAD_PER_HAND, LOAD_ASSISTED, LOAD_BODYWEIGHT, LOAD_STACK,
})

# Conventions whose numbers can be compared across exercises as external
# load. `assisted` cannot (more assistance is less work), `bodyweight` has no
# external load at all, and `stack` numbers are machine-specific.
COMPARABLE_LOAD_CONVENTIONS = frozenset({LOAD_TOTAL, LOAD_PER_HAND})

# Visibility, from revision 159. `unscoped` is the pre-classification state
# and is NOT the same as global.
VISIBILITY_UNSCOPED = "unscoped"
VISIBILITY_GLOBAL = "global"
VISIBILITY_PRIVATE = "private"
VISIBILITY_SHARED = "shared"


class AmbiguousExercise(Exception):
    """One normalized name maps to several canonical exercises.

    Carries the candidates so the caller can ask rather than guess. "Bench"
    when both a barbell and a dumbbell bench exist is this.
    """

    def __init__(self, query: str, candidates: Sequence["ExerciseRef"]):
        super().__init__(
            f"{query!r} could mean "
            + " or ".join(c.name for c in candidates)
        )
        self.query = query
        self.candidates = list(candidates)


@dataclass(frozen=True)
class ExerciseRef:
    """A canonical exercise, with everything a comparison needs."""
    id: str
    name: str
    normalized_name: str
    movement_pattern: Optional[str]
    load_convention: Optional[str]
    parent_exercise_id: Optional[str]
    variation_code: Optional[str]
    is_unilateral: Optional[bool]
    primary_muscles: Tuple[str, ...] = ()
    secondary_muscles: Tuple[str, ...] = ()
    visibility: str = VISIBILITY_UNSCOPED
    owner_user_id: Optional[str] = None

    @property
    def load_is_comparable(self) -> bool:
        """Whether this exercise's load can enter a tonnage or e1RM figure.

        False for assisted, bodyweight and machine-stack conventions, and
        false when the convention was never recorded — an unknown convention
        is not an assumption of `total`.
        """
        return self.load_convention in COMPARABLE_LOAD_CONVENTIONS


@dataclass
class BackfillReport:
    """What a canonical-identity backfill did, or would do."""
    dry_run: bool
    scanned: int = 0
    resolved: int = 0
    ambiguous: int = 0
    unresolved: int = 0
    unresolved_names: List[str] = field(default_factory=list)
    ambiguous_names: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "scanned": self.scanned,
            "resolved": self.resolved,
            "ambiguous": self.ambiguous,
            "unresolved": self.unresolved,
            # Capped: a report is for a human, and a thousand names is not.
            "unresolved_names": sorted(set(self.unresolved_names))[:50],
            "ambiguous_names": sorted(set(self.ambiguous_names))[:50],
        }


_REF_COLUMNS = """
    e.id, e.name, e.normalized_name, e.movement_pattern, e.load_convention,
    e.parent_exercise_id, e.variation_code, e.is_unilateral,
    e.primary_muscles, e.secondary_muscles, e.visibility, e.owner_user_id
"""


def _ref(row: Any) -> ExerciseRef:
    m = dict(row._mapping)
    return ExerciseRef(
        id=m["id"],
        name=m["name"],
        normalized_name=m.get("normalized_name") or normalize_code(m["name"]),
        movement_pattern=m.get("movement_pattern"),
        load_convention=m.get("load_convention"),
        parent_exercise_id=m.get("parent_exercise_id"),
        variation_code=m.get("variation_code"),
        is_unilateral=m.get("is_unilateral"),
        primary_muscles=tuple(m.get("primary_muscles") or ()),
        secondary_muscles=tuple(m.get("secondary_muscles") or ()),
        visibility=m.get("visibility") or VISIBILITY_UNSCOPED,
        owner_user_id=m.get("owner_user_id"),
    )


# ─────────────────────────────────────────────────────────────────────────
# Resolution
# ─────────────────────────────────────────────────────────────────────────

def resolve_exercise(
    db: Session,
    user_id: str,
    query: str,
    *,
    locale: str = "en",
) -> Optional[ExerciseRef]:
    """The canonical exercise a name refers to, or None.

    Exact match on the normalized string, through reviewed aliases only.
    Raises `AmbiguousExercise` when several reviewed aliases in scope
    disagree — returning one of them by insertion order is the silent merge
    this whole module exists to prevent.

    Scope: the athlete's own aliases outrank global ones (they named it), and
    a private exercise belonging to someone else is invisible.
    """
    uid = _require_user(user_id)
    normalized = normalize_code(query)
    if not normalized:
        return None

    rows = db.execute(text(f"""
        SELECT {_REF_COLUMNS},
               a.owner_user_id AS alias_owner
        FROM fitness_exercise_alias a
        JOIN exercise_library e ON e.id = a.exercise_library_id
        WHERE a.normalized_alias = :alias
          AND a.locale = :locale
          AND a.review_status = 'reviewed'
          AND (a.owner_user_id = :uid OR a.owner_user_id IS NULL)
          AND e.archived_at IS NULL
          AND (e.owner_user_id IS NULL OR e.owner_user_id = :uid)
        ORDER BY a.owner_user_id NULLS LAST
    """), {"alias": normalized, "locale": locale, "uid": uid}).fetchall()

    if rows:
        # The athlete's own alias wins outright: they chose that mapping.
        own = [r for r in rows if r.alias_owner == uid]
        candidates = own or rows

        distinct = {r._mapping["id"]: _ref(r) for r in candidates}
        if len(distinct) > 1:
            # Defence in depth. `uq_exercise_alias_scope` makes two reviewed
            # aliases for one normalized string in one scope impossible, and
            # own-beats-global settles the cross-scope case — so reaching
            # here means that index is gone or a new scope was added. Refuse
            # rather than pick by row order.
            raise AmbiguousExercise(
                query, sorted(distinct.values(), key=lambda c: c.name)
            )
        return next(iter(distinct.values()))

    # No alias. Fall back to exercises whose own normalized name matches —
    # which is where the real ambiguity lives.
    #
    # Migration 165 deliberately does NOT seed a self-alias for a name two
    # rows share, because picking one would be the silent merge this module
    # exists to prevent. Without this branch those names resolve to None,
    # which throws away the fact that there ARE candidates and leaves the
    # caller unable to ask.
    by_name = db.execute(text(f"""
        SELECT {_REF_COLUMNS} FROM exercise_library e
        WHERE e.normalized_name = :name
          AND e.archived_at IS NULL
          AND (e.owner_user_id IS NULL OR e.owner_user_id = :uid)
    """), {"name": normalized, "uid": uid}).fetchall()
    if not by_name:
        return None
    # An athlete's own exercise outranks a global one of the same name.
    refs = [_ref(r) for r in by_name]
    own_refs = [r for r in refs if r.owner_user_id == uid]
    chosen = own_refs or refs
    if len(chosen) > 1:
        raise AmbiguousExercise(query, sorted(chosen, key=lambda c: c.name))
    return chosen[0]


def suggest_exercises(
    db: Session,
    user_id: str,
    query: str,
    *,
    limit: int = 8,
) -> List[ExerciseRef]:
    """Candidates for a name that did not resolve exactly.

    For a human to choose from. Deliberately separate from `resolve_exercise`
    and never consulted by it: a substring match is a guess, and a guess that
    silently becomes a logged set's identity misattributes a PR.
    """
    uid = _require_user(user_id)
    normalized = normalize_code(query)
    if not normalized:
        return []
    # Match on any normalized token, so "incline bench" surfaces "Incline
    # Barbell Bench Press" without claiming they are the same thing.
    tokens = [t for t in normalized.split("_") if len(t) > 2] or [normalized]
    pattern = "%" + "%".join(tokens) + "%"

    rows = db.execute(text(f"""
        SELECT {_REF_COLUMNS}
        FROM exercise_library e
        WHERE e.archived_at IS NULL
          AND (e.owner_user_id IS NULL OR e.owner_user_id = :uid)
          AND (e.normalized_name LIKE :pattern
               OR EXISTS (
                   SELECT 1 FROM fitness_exercise_alias a
                   WHERE a.exercise_library_id = e.id
                     AND a.normalized_alias LIKE :pattern
                     AND (a.owner_user_id = :uid OR a.owner_user_id IS NULL)
               ))
        ORDER BY LENGTH(e.normalized_name), e.name
        LIMIT :lim
    """), {"pattern": pattern, "uid": uid, "lim": min(int(limit), 25)}).fetchall()
    return [_ref(r) for r in rows]


def get_exercise(db: Session, user_id: str, exercise_id: str) -> Optional[ExerciseRef]:
    """One canonical exercise by id, respecting visibility."""
    uid = _require_user(user_id)
    row = db.execute(text(f"""
        SELECT {_REF_COLUMNS} FROM exercise_library e
        WHERE e.id = :eid
          AND (e.owner_user_id IS NULL OR e.owner_user_id = :uid)
    """), {"eid": exercise_id, "uid": uid}).fetchone()
    return _ref(row) if row else None


def list_exercises(
    db: Session,
    user_id: str,
    *,
    include_archived: bool = False,
    limit: int = 500,
) -> List[ExerciseRef]:
    """The catalog this athlete can see.

    Global and unscoped rows plus their own private ones. Another athlete's
    private exercise is absent — its name is something they wrote.
    """
    uid = _require_user(user_id)
    archived = "" if include_archived else "AND e.archived_at IS NULL"
    rows = db.execute(text(f"""
        SELECT {_REF_COLUMNS} FROM exercise_library e
        WHERE (e.owner_user_id IS NULL OR e.owner_user_id = :uid) {archived}
        ORDER BY e.name
        LIMIT :lim
    """), {"uid": uid, "lim": min(int(limit), 2000)}).fetchall()
    return [_ref(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────
# Aliases
# ─────────────────────────────────────────────────────────────────────────

def add_alias(
    db: Session,
    user_id: str,
    alias: str,
    exercise_id: str,
    *,
    scope_global: bool = False,
    locale: str = "en",
    source: str = "manual",
) -> str:
    """Map a name to a canonical exercise.

    Refuses when the normalized alias already resolves to a *different*
    exercise in the same scope. That is a genuine ambiguity, and silently
    replacing the existing mapping would retroactively move every set logged
    under that name.

    `scope_global` is deliberately not something an ordinary athlete can set
    through the API — a global alias affects everyone, so the route layer
    requires an admin check for it.
    """
    uid = _require_user(user_id)
    normalized = normalize_code(alias)
    if not normalized:
        raise FitnessDataError("an alias needs at least one alphanumeric character")

    target = get_exercise(db, uid, exercise_id)
    if target is None:
        raise LookupError("exercise not found")
    if target.owner_user_id is not None and target.owner_user_id != uid:
        raise LookupError("exercise not found")
    if scope_global and target.owner_user_id is not None:
        raise FitnessDataError(
            "a global alias cannot point at one athlete's private exercise"
        )

    owner = None if scope_global else uid
    existing = db.execute(text("""
        SELECT id, exercise_library_id FROM fitness_exercise_alias
        WHERE normalized_alias = :alias AND locale = :locale
          AND COALESCE(owner_user_id, '') = COALESCE(:owner, '')
          AND review_status = 'reviewed'
    """), {"alias": normalized, "locale": locale, "owner": owner}).fetchone()
    if existing:
        if existing.exercise_library_id == exercise_id:
            return existing.id
        raise FitnessDataError(
            f"{alias!r} already means something else here; every set logged "
            "under that name would move if this were replaced"
        )

    alias_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_exercise_alias
            (id, normalized_alias, display_alias, exercise_library_id,
             owner_user_id, locale, review_status, source, reviewed_by, reviewed_at)
        VALUES (:id, :alias, :display, :eid, :owner, :locale,
                'reviewed', :source, :uid, NOW())
    """), {
        "id": alias_id, "alias": normalized, "display": alias.strip(),
        "eid": exercise_id, "owner": owner, "locale": locale,
        "source": source, "uid": uid,
    })
    db.commit()
    return alias_id


def record_inferred_alias(
    db: Session,
    user_id: str,
    alias: str,
    exercise_id: str,
    *,
    locale: str = "en",
) -> str:
    """Note a plausible mapping for a human to review later.

    Stored with `review_status='inferred'`, which the lookup index and the
    resolver both exclude. Nothing resolves through one of these, by
    construction rather than by convention — which is what keeps an
    automated suggestion from becoming an athlete's exercise identity.
    """
    uid = _require_user(user_id)
    normalized = normalize_code(alias)
    if not normalized:
        raise FitnessDataError("an alias needs at least one alphanumeric character")
    alias_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_exercise_alias
            (id, normalized_alias, display_alias, exercise_library_id,
             owner_user_id, locale, review_status, source)
        VALUES (:id, :alias, :display, :eid, :uid, :locale, 'inferred', 'suggested')
    """), {
        "id": alias_id, "alias": normalized, "display": alias.strip(),
        "eid": exercise_id, "uid": uid, "locale": locale,
    })
    return alias_id


def list_aliases(
    db: Session, user_id: str, exercise_id: str
) -> List[Dict[str, Any]]:
    uid = _require_user(user_id)
    rows = db.execute(text("""
        SELECT id, normalized_alias, display_alias, owner_user_id, locale,
               review_status, source
        FROM fitness_exercise_alias
        WHERE exercise_library_id = :eid
          AND (owner_user_id = :uid OR owner_user_id IS NULL)
        ORDER BY owner_user_id NULLS FIRST, normalized_alias
    """), {"eid": exercise_id, "uid": uid}).fetchall()
    return [dict(r._mapping) for r in rows]


# ─────────────────────────────────────────────────────────────────────────
# Custom exercises and scope
# ─────────────────────────────────────────────────────────────────────────

def create_custom_exercise(
    db: Session,
    user_id: str,
    name: str,
    *,
    movement_pattern: str = "other",
    load_convention: str = LOAD_TOTAL,
    parent_exercise_id: Optional[str] = None,
    variation_code: Optional[str] = None,
    is_unilateral: bool = False,
    primary_muscles: Optional[Sequence[str]] = None,
    secondary_muscles: Optional[Sequence[str]] = None,
    rom_notes: Optional[str] = None,
) -> ExerciseRef:
    """A private exercise, visible only to this athlete.

    `visibility='private'` with an owner, which revision 159's constraint
    requires together. Private by default is the point: the name is
    something the athlete wrote, and publishing it globally would expose it.
    """
    import json

    uid = _require_user(user_id)
    if load_convention not in VALID_LOAD_CONVENTIONS:
        raise FitnessDataError(
            f"{load_convention!r} is not a load convention "
            f"({', '.join(sorted(VALID_LOAD_CONVENTIONS))})"
        )
    normalized = normalize_code(name)
    if not normalized:
        raise FitnessDataError("an exercise needs a name")

    if parent_exercise_id is not None:
        parent = get_exercise(db, uid, parent_exercise_id)
        if parent is None:
            raise LookupError("parent exercise not found")

    # A name this athlete can already resolve would make the new row
    # unreachable by name, and the alias insert below would fail anyway.
    try:
        existing = resolve_exercise(db, uid, name)
    except AmbiguousExercise:
        existing = None
    if existing is not None:
        raise FitnessDataError(
            f"{name!r} already resolves to {existing.name!r} for you"
        )

    eid = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO exercise_library
            (id, name, normalized_name, movement_pattern, load_convention,
             parent_exercise_id, variation_code, is_unilateral,
             primary_muscles, secondary_muscles, rom_notes,
             owner_user_id, visibility, created_at, updated_at)
        VALUES (:id, :name, :norm, :pattern, :convention, :parent, :variation,
                :unilateral, CAST(:primary AS jsonb), CAST(:secondary AS jsonb),
                :rom, :uid, 'private', NOW(), NOW())
    """), {
        "id": eid, "name": name.strip(), "norm": normalized,
        "pattern": movement_pattern, "convention": load_convention,
        "parent": parent_exercise_id, "variation": variation_code,
        "unilateral": is_unilateral,
        "primary": json.dumps(list(primary_muscles or [])),
        "secondary": json.dumps(list(secondary_muscles or [])),
        "rom": rom_notes, "uid": uid,
    })
    db.execute(text("""
        INSERT INTO fitness_exercise_alias
            (id, normalized_alias, display_alias, exercise_library_id,
             owner_user_id, locale, review_status, source, reviewed_by, reviewed_at)
        VALUES (:aid, :norm, :name, :eid, :uid, 'en', 'reviewed', 'self_name',
                :uid, NOW())
    """), {"aid": str(uuid.uuid4()), "norm": normalized, "name": name.strip(),
           "eid": eid, "uid": uid})
    db.commit()

    created = get_exercise(db, uid, eid)
    assert created is not None
    return created


def classify_visibility(
    db: Session, *, dry_run: bool = True
) -> Dict[str, Any]:
    """Classify `unscoped` exercises from who has actually logged them.

    The table has no owner column of its own and
    `exercise_library_seed.py` derived rows from names already present in
    people's logs, so provenance is only knowable from usage:

    * nobody has logged it   → `global`. No private history attached, so it
      is safe as a shared seed.
    * exactly one athlete    → `private` to them. Publishing it would expose
      a user-created exercise name.
    * several athletes       → `shared`, which is **not** public. It stays
      restricted pending review; "two people used it" is not consent to
      publish.

    Dry-run by default. Returns counts, never names — a single-user name is
    private and must not appear in a report.
    """
    rows = db.execute(text("""
        WITH usage AS (
            SELECT e.id,
                   COUNT(DISTINCT w.user_id) AS users,
                   MIN(w.user_id) AS sole_user
            FROM exercise_library e
            LEFT JOIN workout_log w
              ON w.exercise_library_id = e.id
              OR LOWER(TRIM(w.exercise_id)) = LOWER(TRIM(e.name))
            WHERE e.visibility = 'unscoped' AND e.archived_at IS NULL
            GROUP BY e.id
        )
        SELECT id, users, sole_user FROM usage
    """)).fetchall()

    plan = {"global": [], "private": [], "shared": []}
    for row in rows:
        if row.users == 0:
            plan["global"].append((row.id, None))
        elif row.users == 1:
            plan["private"].append((row.id, row.sole_user))
        else:
            plan["shared"].append((row.id, None))

    if not dry_run:
        for eid, _ in plan["global"]:
            db.execute(text("""
                UPDATE exercise_library
                SET visibility = 'global', owner_user_id = NULL,
                    scope_reviewed_at = NOW()
                WHERE id = :id AND visibility = 'unscoped'
            """), {"id": eid})
        for eid, owner in plan["private"]:
            if not owner:
                continue
            # The owner must be a real app_user: a solo-era string like
            # `default-user` is an unresolved orphan (migration 159's
            # quarantine), and assigning the exercise to it would fail the FK
            # or, worse, pretend the question was settled.
            real = db.execute(text(
                "SELECT 1 FROM app_user WHERE id = :id"), {"id": owner}).fetchone()
            if not real:
                continue
            db.execute(text("""
                UPDATE exercise_library
                SET visibility = 'private', owner_user_id = :owner,
                    scope_reviewed_at = NOW()
                WHERE id = :id AND visibility = 'unscoped'
            """), {"id": eid, "owner": owner})
        for eid, _ in plan["shared"]:
            db.execute(text("""
                UPDATE exercise_library
                SET visibility = 'shared', scope_reviewed_at = NOW()
                WHERE id = :id AND visibility = 'unscoped'
            """), {"id": eid})

    return {
        "dry_run": dry_run,
        "global": len(plan["global"]),
        "private": len(plan["private"]),
        "shared": len(plan["shared"]),
        "note": (
            "shared is restricted, not public: two athletes using a name is "
            "not consent to publish it"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────
# Backfill
# ─────────────────────────────────────────────────────────────────────────

def backfill_canonical_ids(
    db: Session,
    user_id: str,
    *,
    dry_run: bool = True,
    batch_size: int = 500,
) -> BackfillReport:
    """Fill `workout_log.exercise_library_id` where the name resolves exactly.

    Only unambiguous exact matches are written. A name that resolves to
    several candidates, or to none, is reported and **left alone** — the
    legacy text `exercise_id` stays as the fallback identity and analytics
    report it as an unresolved identity.

    Guessing here would attribute an athlete's sets to a movement they never
    performed, and the mistake would be invisible: the set still shows the
    name they typed while the PR and progression comparisons use a different
    lift's history.

    Idempotent: a second run finds nothing left with a NULL canonical id for
    a resolvable name. Does not commit on a dry run.
    """
    uid = _require_user(user_id)
    report = BackfillReport(dry_run=dry_run)

    rows = db.execute(text("""
        SELECT DISTINCT exercise_id
        FROM workout_log
        WHERE user_id = :uid
          AND exercise_library_id IS NULL
          AND exercise_id IS NOT NULL
          AND TRIM(exercise_id) <> ''
        LIMIT :lim
    """), {"uid": uid, "lim": min(int(batch_size), 5000)}).fetchall()

    for row in rows:
        legacy = row.exercise_id
        report.scanned += 1
        try:
            resolved = resolve_exercise(db, uid, legacy)
        except AmbiguousExercise:
            report.ambiguous += 1
            report.ambiguous_names.append(legacy)
            continue
        if resolved is None:
            report.unresolved += 1
            report.unresolved_names.append(legacy)
            continue

        if not dry_run:
            result = db.execute(text("""
                UPDATE workout_log
                SET exercise_library_id = :eid
                WHERE user_id = :uid
                  AND exercise_library_id IS NULL
                  AND exercise_id = :legacy
            """), {"eid": resolved.id, "uid": uid, "legacy": legacy})
            report.resolved += result.rowcount
        else:
            count = db.execute(text("""
                SELECT COUNT(*) FROM workout_log
                WHERE user_id = :uid
                  AND exercise_library_id IS NULL
                  AND exercise_id = :legacy
            """), {"uid": uid, "legacy": legacy}).scalar()
            report.resolved += int(count or 0)

    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return report


def effective_load_for(
    ref: Optional[ExerciseRef], load: Optional[float]
) -> Tuple[Optional[float], Optional[str]]:
    """Total external load implied by a recorded number, and why not.

    * `per_hand` doubles: 40 kg dumbbells is 80 kg moved.
    * `assisted` is refused. More assistance is *less* work, so treating the
      number as load would rank an easier set higher.
    * `bodyweight` has no external load to report.
    * `stack` numbers are machine-specific and not comparable to a barbell.
    * An unrecorded convention is refused rather than assumed to be `total`.

    The second element is the reason the load is unavailable, for a `Metric`
    to carry.
    """
    if load is None:
        return None, "no load recorded"
    if ref is None or ref.load_convention is None:
        return None, "the exercise's load convention was never recorded"
    if ref.load_convention == LOAD_PER_HAND:
        return load * 2, None
    if ref.load_convention == LOAD_TOTAL:
        return load, None
    if ref.load_convention == LOAD_ASSISTED:
        return None, "assisted load is not external load — more help is less work"
    if ref.load_convention == LOAD_BODYWEIGHT:
        return None, "bodyweight movement has no external load"
    if ref.load_convention == LOAD_STACK:
        return None, "machine stack numbers are not comparable to free weight"
    return None, f"unknown load convention {ref.load_convention!r}"


def share_comparison_identity(a: ExerciseRef, b: ExerciseRef) -> bool:
    """Whether two exercises may share a PR or a progression comparison.

    Only identity. Not the parent: barbell and dumbbell bench share a
    movement parent so "how much horizontal pressing" is answerable, and
    they must never share a record — the dumbbell PR would be credited to
    the barbell.
    """
    return a.id == b.id
