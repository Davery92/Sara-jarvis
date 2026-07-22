"""Graduated autonomy / trust matrix (§3.7) — the trust contract, made explicit.

Every *action class* sits at a trust level:
  L0 observe (log only) → L1 suggest (attention item) → L2 act-and-tell (do it;
  notify) → L3 act-silently (do it; ledger only).

Levels are both **granted** by David (a visible ceiling he sets per class) and
**earned** — promotion eligibility requires a track record (N executions, zero
unresolved failures, high acceptance); demotion is automatic on failure/override.
Higher autonomy ⇒ louder failure (the B7 lock lesson generalized): an L3 class
that fails reports at L2 volume.

This is the substrate the standing-order ladder (Phase 3) and the delivery
policy plug into; it does not itself execute — it decides how loud an action of
a given class is allowed to be.
"""
import logging
from typing import Dict, Any, List

from sqlalchemy import text

logger = logging.getLogger(__name__)

_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

L0, L1, L2, L3 = 0, 1, 2, 3

# Default granted ceilings — conservative. David raises them in Settings (§7.6).
_DEFAULT_CLASSES = {
    "home_lights": L2,       # low-stakes, reversible → act-and-tell by default
    "home_locks": L1,        # security → suggest only until earned + granted
    "notifications": L2,     # she already sends; act-and-tell
    "calendar_write": L1,
    "reminders": L2,
    "research": L2,          # read-only effector
    "email_draft": L1,       # compose only; David sends
    "code_change": L0,       # never autonomous (local-first policy)
}

# Earn thresholds for eligibility to be promoted one level.
_EARN_MIN_EXECUTIONS = 20
_EARN_MIN_ACCEPTANCE = 0.8


async def ensure_seeded(db):
    for cls, lvl in _DEFAULT_CLASSES.items():
        await db.execute(text("""
            INSERT INTO autonomy_trust (action_class, granted_level, updated_at)
            VALUES (:c, :l, NOW())
            ON CONFLICT (action_class) DO NOTHING
        """), {"c": cls, "l": lvl})
    await db.commit()


async def granted_level(db, action_class: str) -> int:
    r = (await db.execute(text(
        "SELECT granted_level FROM autonomy_trust WHERE action_class = :c"
    ), {"c": action_class})).first()
    return int(r[0]) if r else _DEFAULT_CLASSES.get(action_class, L1)


async def set_granted_level(db, action_class: str, level: int) -> dict:
    level = max(L0, min(L3, int(level)))
    await db.execute(text("""
        INSERT INTO autonomy_trust (action_class, granted_level, updated_at)
        VALUES (:c, :l, NOW())
        ON CONFLICT (action_class)
        DO UPDATE SET granted_level = :l, updated_at = NOW()
    """), {"c": action_class, "l": level})
    await db.commit()
    logger.info(f"🔐 Trust: {action_class} granted L{level}")
    return {"action_class": action_class, "granted_level": level}


async def record_outcome(db, action_class: str, success: bool, accepted: bool = None):
    """Update a class's track record. Auto-demote one level on failure."""
    await db.execute(text("""
        INSERT INTO autonomy_trust (action_class, executions, failures, updated_at)
        VALUES (:c, 1, :f, NOW())
        ON CONFLICT (action_class) DO UPDATE SET
            executions = autonomy_trust.executions + 1,
            failures = autonomy_trust.failures + :f,
            updated_at = NOW()
    """), {"c": action_class, "f": 0 if success else 1})
    if accepted is not None:
        col = "accepts" if accepted else "declines"
        await db.execute(text(
            f"UPDATE autonomy_trust SET {col} = {col} + 1 WHERE action_class = :c"
        ), {"c": action_class})
    if not success:
        # Automatic demotion — higher autonomy must be re-earned after a failure.
        await db.execute(text("""
            UPDATE autonomy_trust
            SET granted_level = GREATEST(0, granted_level - 1), last_demoted_at = NOW()
            WHERE action_class = :c AND granted_level > 1
        """), {"c": action_class})
    await db.commit()


def _acceptance(accepts: int, declines: int) -> float:
    total = accepts + declines
    return accepts / total if total else 0.0


async def get_matrix(db) -> List[Dict[str, Any]]:
    """The full trust matrix for the webapp console (§7.3)."""
    await ensure_seeded(db)
    rows = (await db.execute(text("""
        SELECT action_class, granted_level, executions, failures, accepts, declines,
               last_demoted_at
        FROM autonomy_trust ORDER BY action_class
    """))).fetchall()
    out = []
    for r in rows:
        acceptance = _acceptance(r.accepts or 0, r.declines or 0)
        unresolved_failures = (r.failures or 0)
        eligible = (
            (r.executions or 0) >= _EARN_MIN_EXECUTIONS
            and unresolved_failures == 0
            and acceptance >= _EARN_MIN_ACCEPTANCE
            and (r.granted_level or 0) < L3
        )
        out.append({
            "action_class": r.action_class,
            "granted_level": r.granted_level,
            "executions": r.executions or 0,
            "failures": r.failures or 0,
            "acceptance_rate": round(acceptance, 2),
            "promotion_eligible": eligible,
            "last_demoted_at": r.last_demoted_at.isoformat() if r.last_demoted_at else None,
        })
    return out
