"""
Feature flags / kill switches (SINGULAR_SARA_MASTER_PLAN §13/§C0).

"Define feature flags and kill switches" — one per migration surface — so a
cutover (§10: "Roll out... one state at a time") is a config change instead
of a code change, and a bad cutover is a reversible flip instead of a
revert-and-redeploy.

Backed by the existing `app_settings` key-value table (same read pattern as
`llm_broker._get_settings`) so a flag can change from the settings UI/API
without a backend restart. Every flag defaults OFF: nothing in this
migration has cut over yet (per §13's first slice: "Run without changing
cognition or delivery behavior"), and a missing row must fail toward the
legacy path, never toward an unreviewed cutover.

Nothing in the codebase branches on these flags yet — this module only
defines them. Each C-phase wires its own flag in when it actually introduces
a target path to switch to.
"""

import logging
from enum import Enum
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class Flag(str, Enum):
    SINGULAR_EVENT_ENVELOPE = "SINGULAR_EVENT_ENVELOPE"
    SINGULAR_CONTEXT = "SINGULAR_CONTEXT"
    SINGULAR_INTENTS = "SINGULAR_INTENTS"
    SINGULAR_KERNEL = "SINGULAR_KERNEL"
    SINGULAR_VM_BODY = "SINGULAR_VM_BODY"
    SINGULAR_ATTENTION = "SINGULAR_ATTENTION"
    SINGULAR_ACTIONS = "SINGULAR_ACTIONS"
    LEGACY_COGNITION_SHADOW = "LEGACY_COGNITION_SHADOW"

    # Apple Watch / cross-device workout (SARA_APPLE_WATCH_FITNESS_IMPLEMENTATION_PLAN §13 P0).
    # All three default OFF: the v2 command path, the Watch surface, and native
    # coaching audio each roll out independently, and flipping any of them off
    # must leave the existing phone workout untouched (§16.2 rollback).
    WATCH_WORKOUT_ENABLED = "WATCH_WORKOUT_ENABLED"
    WORKOUT_COMMAND_V2_ENABLED = "WORKOUT_COMMAND_V2_ENABLED"
    WORKOUT_COACHING_AUDIO_ENABLED = "WORKOUT_COACHING_AUDIO_ENABLED"

    # SARA_MIND_V2_PLAN §6 — each gates one phase of the Jarvis-grade rebuild.
    # Feature-flag-per-phase, overlap window with counters, then hard
    # deletion in Phase 5 (D3) — same cutover discipline as SINGULAR_*.
    MINDV2_BRIEF = "MINDV2_BRIEF"          # Phase 1: World Brief feeds chat context (A/B, additive)
    MINDV2_COMPOSE = "MINDV2_COMPOSE"      # Phase 2: Judge/Compose/Review own outbound delivery
    MINDV2_APPRAISAL = "MINDV2_APPRAISAL"  # Phase 3: appraisal loop replaces salience/deliberation
    MINDV2_ACT = "MINDV2_ACT"              # Phase 4: act-then-speak prep dispatch + commitments


ALL_FLAGS: List[str] = [f.value for f in Flag]
_TRUE_VALUES = {"1", "true", "yes", "on"}
FlagLike = Union["Flag", str]


def _flag_name(flag: FlagLike) -> str:
    name = flag.value if isinstance(flag, Flag) else str(flag)
    if name not in ALL_FLAGS:
        raise ValueError(f"unknown feature flag: {name!r} (known: {ALL_FLAGS})")
    return name


def _read_flags(keys: Optional[List[str]] = None) -> Dict[str, str]:
    keys = keys or ALL_FLAGS
    try:
        from sqlalchemy import text
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            rows = db.execute(
                text("SELECT key, value FROM app_settings WHERE key = ANY(:keys)"),
                {"keys": keys},
            ).fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[feature_flags] read failed: {e}")
        return {}


def is_enabled(flag: FlagLike) -> bool:
    """True only if the row exists and is explicitly truthy. Missing row or
    a read failure both resolve to False — fail toward the legacy path."""
    name = _flag_name(flag)
    value = _read_flags([name]).get(name)
    return (value or "").strip().lower() in _TRUE_VALUES


def all_flags() -> Dict[str, bool]:
    """Snapshot of every flag's current state, for the diagnostics endpoint
    and for anything checking 'what's actually live right now' before
    trusting a rollout-stage claim."""
    values = _read_flags()
    return {name: (values.get(name) or "").strip().lower() in _TRUE_VALUES for name in ALL_FLAGS}


def set_flag(flag: FlagLike, enabled: bool, updated_by: str = "system") -> None:
    """Flip a flag. For the settings UI/API and tests — the migration itself
    doesn't call this (nothing has cut over yet)."""
    name = _flag_name(flag)
    from sqlalchemy import text
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO app_settings (key, value, updated_by)
            VALUES (:key, :value, :updated_by)
            ON CONFLICT (key) DO UPDATE
                SET value = :value, updated_by = :updated_by, updated_at = CURRENT_TIMESTAMP
        """), {"key": name, "value": "true" if enabled else "false", "updated_by": updated_by})
        db.commit()
    finally:
        db.close()
