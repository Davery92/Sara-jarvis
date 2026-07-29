"""The Self-Model (§3.4) — Sara knows herself.

A continuously-derivable, queryable model of Sara *herself*: her health (what's
broken right now), her calibration (how accurate her predictions are), her
capabilities (which actuators work), and her deploy state. The acceptance test
from the audit is literal: **Sara could have produced Part 1 of the audit from
this** — every finding there was derivable from data she already stores.

This is *Sara's* input, not just a status page: chat introspects it ("my
sent-mail sync has been stalled 16 days, so I may have missed commitments"),
deliberation weighs it (don't promise research if the research worker is
failing), and the delivery policy can consult channel health.

Read-only. Assembles from task_failure, scheduled_job, email_sync_state, the
prediction calibration (§3.9), push tokens, the ML registry, and the ACS daemon
heartbeat. Never mutates — honesty, not action.
"""
import logging
from typing import Dict, Any, List

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Daemon heartbeat older than this = the ACS locus of continuity is down.
_DAEMON_STALE_MIN = 30


_COMPONENT_KIND_PREFIXES = {
    "task_failure:": "task_failure",
    "scheduled_job:": "scheduled_job_failed",
    "email_cursor:": "stalled_cursor",
}


def _kind_for_component(name: str, source: str) -> str:
    for prefix, kind in _COMPONENT_KIND_PREFIXES.items():
        if name.startswith(prefix):
            return kind
    return source  # system_heartbeat / interoception components, new here


async def _health(db, user_id: str) -> Dict[str, Any]:
    """Arc 2.2 (SARA_ALIVE_BUILD_PLAN): this used to run its own independent
    checks (task_failure, scheduled_job, email_sync_state) — found live to
    disagree with /api/sara/brief's self_status in the same minute, because
    that endpoint reads body_state_projection.get_body_state_projection()
    and this one never did. Now reads the same canonical projection (which
    itself folds these exact checks back in — see
    body_state_projection._load_self_model_health_components) so the two
    surfaces can't diverge again. Shape unchanged for existing callers;
    `issues` is now a superset (also surfaces system_heartbeat/interoception
    degradation this function never used to see)."""
    from app.services.body_state_projection import get_body_state_projection

    projection = await get_body_state_projection(user_id)
    issues: List[Dict[str, Any]] = [
        {
            "kind": _kind_for_component(c.name, c.source),
            "severity": c.severity or "warning",
            "what": c.label or c.name,
            "detail": c.impact,
            "since": c.as_of.isoformat() if c.as_of else None,
        }
        for c in projection.components
        if c.status.value == "degraded"
    ]
    return {"ok": len(issues) == 0, "issue_count": len(issues), "issues": issues}


async def _calibration(db, user_id: str) -> Dict[str, Any]:
    try:
        from app.services.prediction_engine import compute_calibration
        return await compute_calibration(db, user_id, days=30)
    except Exception as e:
        logger.debug(f"self_model calibration skipped: {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        return {"error": "unavailable"}


async def _capabilities(db, user_id: str) -> Dict[str, Any]:
    caps: Dict[str, Any] = {}
    # Push channel.
    n_tokens = (await db.execute(text(
        "SELECT COUNT(*) FROM push_token WHERE user_id = :u"
    ), {"u": user_id})).scalar() or 0
    caps["push"] = {"functional": n_tokens > 0, "tokens": int(n_tokens)}

    # Learned notification-value model.
    mv = (await db.execute(text("""
        SELECT version, metrics FROM ml_model_version
        WHERE family = 'notification_value' AND status = 'active'
        ORDER BY activated_at DESC NULLS LAST LIMIT 1
    """))).first()
    caps["notification_value_model"] = {
        "trained": mv is not None,
        "version": mv[0] if mv else None,
    }

    # Prediction loop activity.
    pend = (await db.execute(text(
        "SELECT COUNT(*) FROM prediction WHERE outcome = 'pending'"
    ))).scalar() or 0
    caps["prediction_loop"] = {"pending_predictions": int(pend)}

    return caps


async def _deploy(db) -> Dict[str, Any]:
    row = (await db.execute(text("""
        SELECT version, state, last_heartbeat_at
        FROM sara_daemon_state
        ORDER BY updated_at DESC NULLS LAST LIMIT 1
    """))).first()
    if not row:
        return {"acs_daemon": {"alive": False, "reason": "no_state_row"}}
    version, state, hb = row
    stale = True
    minutes = None
    if hb:
        minutes = (local_now() - hb.astimezone(local_now().tzinfo)).total_seconds() / 60.0 \
            if hb.tzinfo else None
        try:
            from app.core.timezone import to_naive_utc
            minutes = (to_naive_utc(local_now()) - to_naive_utc(hb)).total_seconds() / 60.0
        except Exception:
            pass
        stale = minutes is not None and minutes > _DAEMON_STALE_MIN
    return {"acs_daemon": {
        "alive": not stale, "version": version, "state": state,
        "heartbeat_minutes_ago": round(minutes, 1) if minutes is not None else None,
    }}


async def build_self_model(db, user_id: str = _DAVID) -> Dict[str, Any]:
    """Assemble the full self-model. Read-only."""
    health = await _health(db, user_id)
    return {
        "generated_at": local_now().isoformat(),
        "health": health,
        "calibration": await _calibration(db, user_id),
        "capabilities": await _capabilities(db, user_id),
        "deploy": await _deploy(db),
        "summary": _summarize(health),
    }


def _summarize(health: Dict[str, Any]) -> str:
    """One-line honest self-assessment, chat-ready."""
    if health["ok"]:
        return "Everything's wired and running — no unresolved failures, stalls, or stale cursors."
    n = health["issue_count"]
    top = health["issues"][0]["what"] if health["issues"] else "something"
    return f"{n} thing{'s' if n != 1 else ''} need attention right now — most notably: {top}."


async def self_health_line(db, user_id: str = _DAVID) -> str:
    """Cheap one-liner for chat introspection / caveats."""
    health = await _health(db, user_id)
    return _summarize(health)
