"""
Body-sense — Sara's interoception of her own bodies and vital signs.

ONE_MIND §3.1: her own bodies (hosts), jobs, and vital signs become events on
the *same* afferent pathway as everything else. Before this, system health was a
department: the heartbeat task pushed a raw alert into a log nobody reads, and
when the sara-VM lost power it was dead 23+ hours and nothing in Sara noticed.

This service turns the heartbeat's health report — plus ACS-daemon liveness and
managed-host reachability — into first-class events (`SYSTEM_HEALTH_DEGRADED` /
`SYSTEM_HEALTH_RECOVERED`) on the event bus, so they flow through salience →
observation log → deliberation like any other sense. It *also* composes and
sends the human-facing alert through the one attention economy
(`send_notification`), so David is told in Sara's one voice, ledgered and
cooldown-gated, rather than by a raw f-string.

(Distinct from `interoception.py`, which builds the one-line circadian/clock
header for prompts. This module is the *ops* sense: her hosts and jobs.)

Key discipline (feedback_no_repetitive_nags): events fire on **state
transitions only** — a subsystem going down, or coming back — never on every
5-minute tick while a condition persists.
"""

import json
import logging
import os
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Redis key holding the last-known set of degraded subsystems, so we can diff
# tick-over-tick and only surface transitions.
_STATE_KEY = "system:interoception_state"
_ANNOUNCED_KEY = "system:interoception_announced"  # subsystems with an open, delivered alert
_STATE_TTL = 7 * 24 * 3600  # a week; refreshed every tick

# A subsystem is "failed" at these heartbeat statuses (WARNING is too noisy).
_FAILED_STATUSES = {"error", "critical"}

# Daemon is considered silent after this long without a heartbeat. The daemon
# beats every minute or two; 15 min means "it actually went dark," not jitter.
_DAEMON_SILENT_SECONDS = 15 * 60

# Human-readable (name, impact) per subsystem, so Sara says what a failure
# *means*, not just its name.
_SUBSYSTEM_LABEL = {
    "redis": ("my working memory / event bus", "my short-term memory and reactive senses are impaired"),
    "database": ("my long-term memory (Postgres)", "I can't read or write most of what I know"),
    "llm_primary": ("my primary reasoning-model host", "I've fallen back to the smaller, faster model"),
    "llm_fallback": ("my fallback model host", "I've lost my safety net if the primary also drops"),
    "embeddings": ("my semantic memory (embeddings)", "new memories can't be indexed for recall"),
    "consolidation": ("my memory consolidation", "episodes aren't being turned into knowledge"),
    "working_memory": ("my working memory", "my sense of the current situation is degraded"),
    "queue_depths": ("my task queues", "background work is backing up"),
    "acs_daemon": ("my autonomous mind on the sara-VM", "my background and overnight self is offline"),
    "raw_buffer": ("my sensory buffer", "raw audio/screen ingest is impaired"),
}


def _label(subsystem: str) -> Tuple[str, str]:
    """(friendly_name, impact) for a subsystem key. Handles host:<name>."""
    if subsystem.startswith("host:"):
        name = subsystem.split(":", 1)[1]
        return (f"the {name} host", f"I've lost access to {name}")
    return _SUBSYSTEM_LABEL.get(subsystem, (subsystem, "a part of me is degraded"))


async def _get_redis():
    import redis.asyncio as aioredis
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    return aioredis.from_url(redis_url, decode_responses=True)


async def _load_state(r) -> Dict[str, str]:
    """Return {subsystem: severity} from the last tick."""
    try:
        raw = await r.get(_STATE_KEY)
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.debug(f"[body_sense] could not load prior state: {e}")
    return {}


async def _save_state(r, state: Dict[str, str]) -> None:
    try:
        await r.set(_STATE_KEY, json.dumps(state), ex=_STATE_TTL)
    except Exception as e:
        logger.debug(f"[body_sense] could not save state: {e}")


# Subsystems whose degradation alert was actually DELIVERED to David (an "open,
# announced incident"). Only these get an all-clear on recovery — so David is
# never left hanging by an alert that had no close, and never confused by an
# all-clear for a problem he was never told about.
async def _load_announced(r) -> set:
    try:
        h = await r.hgetall(_ANNOUNCED_KEY)
        return set(h.keys()) if h else set()
    except Exception:
        return set()


async def _mark_announced(r, subsystems) -> None:
    try:
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc).isoformat()
        for s in subsystems:
            await r.hset(_ANNOUNCED_KEY, s, now)
        await r.expire(_ANNOUNCED_KEY, _STATE_TTL)
    except Exception as e:
        logger.debug(f"[body_sense] mark_announced failed: {e}")


async def _clear_announced(r, subsystems) -> None:
    try:
        for s in subsystems:
            await r.hdel(_ANNOUNCED_KEY, s)
    except Exception as e:
        logger.debug(f"[body_sense] clear_announced failed: {e}")


async def _check_daemon() -> Optional[str]:
    """Return 'error' if the ACS daemon was alive but went silent, else None.

    Only flags a daemon that *was* beating and stopped — never one that was
    never deployed (NULL heartbeat) — so we don't nag about a limb that
    doesn't exist yet."""
    try:
        from sqlalchemy import text
        from app.db.session import get_async_session_factory
        factory = get_async_session_factory()
        async with factory() as db:
            row = (await db.execute(text(
                "SELECT last_heartbeat_at, "
                "EXTRACT(EPOCH FROM (NOW() - last_heartbeat_at)) AS age "
                "FROM sara_daemon_state WHERE id = 'singleton'"
            ))).mappings().first()
        if not row or row["last_heartbeat_at"] is None:
            return None  # never deployed / never beat → not a regression
        age = row["age"]
        if age is not None and float(age) > _DAEMON_SILENT_SECONDS:
            return "error"
    except Exception as e:
        logger.debug(f"[body_sense] daemon check failed: {e}")
    return None


async def _check_hosts() -> Dict[str, str]:
    """Return {host:<name>: severity} for active managed hosts last seen as
    unreachable/error. Passive: reads the last known status set by the
    host_inspector, does not actively SSH-poll here."""
    out: Dict[str, str] = {}
    try:
        from sqlalchemy import text
        from app.db.session import get_async_session_factory
        factory = get_async_session_factory()
        async with factory() as db:
            rows = (await db.execute(text(
                "SELECT name, last_status FROM managed_host "
                "WHERE active = true AND last_status IN ('unreachable', 'error')"
            ))).mappings().all()
        for r in rows:
            out[f"host:{r['name']}"] = "error"
    except Exception as e:
        logger.debug(f"[body_sense] host check failed: {e}")
    return out


def _failed_from_report(report: Dict[str, Any]) -> Dict[str, str]:
    """Extract {subsystem: severity} for ERROR/CRITICAL checks in a heartbeat
    health report."""
    out: Dict[str, str] = {}
    for name, check in (report.get("checks") or {}).items():
        status = str(check.get("status", "")).lower()
        if status in _FAILED_STATUSES:
            out[name] = status
    return out


def _summarize(subsystems: Dict[str, str]) -> str:
    """One-line human summary of a set of degraded subsystems, for the raw
    (LLM-free) fallback text — must read well even when the reasoning host is
    the thing that's down."""
    names = [_label(s)[0] for s in subsystems]
    if not names:
        return "a subsystem"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"


async def reflect(report: Dict[str, Any], user_id: str = DAVID_USER_ID) -> Dict[str, Any]:
    """Main entry — called by the heartbeat task after it assembles a health
    report. Diffs against the prior tick, emits transition events onto the bus,
    and sends composed alerts through the attention economy.

    Returns a small summary dict (for logging / tests)."""
    # 1. Assemble the full current failed-set from every interoceptive source.
    current: Dict[str, str] = _failed_from_report(report)

    daemon = await _check_daemon()
    if daemon:
        current["acs_daemon"] = daemon

    current.update(await _check_hosts())

    r = await _get_redis()
    prior = await _load_state(r)

    prior_keys = set(prior.keys())
    current_keys = set(current.keys())
    newly_failed = current_keys - prior_keys
    recovered = prior_keys - current_keys

    # 2. Persist current state immediately so a crash mid-alert can't loop.
    await _save_state(r, current)
    announced = await _load_announced(r)

    result = {
        "current": sorted(current_keys),
        "newly_failed": sorted(newly_failed),
        "recovered": sorted(recovered),
        "events": [],
        "alerts": [],
    }

    # 3. Degradation transition — a body/vital just went dark. Remember which
    #    ones we actually reached David about, so we know to close them later.
    if newly_failed:
        worst = "critical" if any(current.get(s) == "critical" for s in newly_failed) else "error"
        delivered = await _emit_and_alert(
            user_id=user_id,
            kind="degraded",
            subsystems={s: current[s] for s in newly_failed},
            severity=worst,
            result=result,
        )
        if delivered:
            await _mark_announced(r, newly_failed)

    # 4. Recovery transition — a body/vital came back. Push an all-clear ONLY
    #    for incidents David was actually alerted about (no orphan "recovered"
    #    for a degradation he never saw). The event still fires for all of them
    #    (kernel awareness); only the push is gated.
    if recovered:
        to_close = {s for s in recovered if s in announced}
        silent = set(recovered) - to_close
        if to_close:
            await _emit_and_alert(
                user_id=user_id, kind="recovered",
                subsystems={s: prior.get(s, "error") for s in to_close},
                severity="normal", result=result, notify=True,
            )
        if silent:
            await _emit_and_alert(
                user_id=user_id, kind="recovered",
                subsystems={s: prior.get(s, "error") for s in silent},
                severity="normal", result=result, notify=False,
            )
        await _clear_announced(r, recovered)

    # Reconcile: `announced` must only ever hold currently-degraded subsystems.
    # Self-heals any entry left behind by a restart race (a transient blip that
    # got announced but whose recovery transition was never cleanly processed),
    # so a stale entry can't linger for its 7-day TTL.
    stale = (await _load_announced(r)) - current_keys
    if stale:
        await _clear_announced(r, stale)

    try:
        await r.close()
    except Exception:
        pass

    if newly_failed or recovered:
        logger.info(
            f"[body_sense] degraded={sorted(newly_failed)} recovered={sorted(recovered)} "
            f"still_down={sorted(current_keys - newly_failed)}"
        )
    return result


async def _emit_and_alert(
    user_id: str,
    kind: str,
    subsystems: Dict[str, str],
    severity: str,
    result: Dict[str, Any],
    notify: bool = True,
) -> bool:
    """Publish the interoception event, and (when notify) send the composed
    human alert. Returns True iff a push was actually delivered to David."""
    summary = _summarize(subsystems)
    impacts = [_label(s)[1] for s in subsystems]
    impact_str = impacts[0] if impacts else ""

    # --- Event onto the bus (→ salience → observation → deliberation) ---
    try:
        from app.services.event_bus import event_bus, Event, EventType
        etype = (
            EventType.SYSTEM_HEALTH_DEGRADED if kind == "degraded"
            else EventType.SYSTEM_HEALTH_RECOVERED
        )
        await event_bus.publish(Event(
            event_type=etype,
            user_id=user_id,
            source="interoception",
            payload={
                "subsystems": list(subsystems.keys()),
                "severity": severity,
                "summary": summary,
                "impact": impact_str,
                "confidence": 1.0,          # measured, not inferred
                "provenance": "system_heartbeat",
            },
        ))
        result["events"].append(f"{etype.value}:{','.join(subsystems.keys())}")
    except Exception as e:
        logger.warning(f"[body_sense] failed to publish {kind} event: {e}")

    # Event-only path (e.g. an un-announced recovery): no push, just awareness.
    if not notify:
        return False

    # --- Composed human alert through the one attention economy ---
    try:
        from app.services.unified_notification import send_notification
        if kind == "degraded":
            title = "Heads up — I'm degraded"
            message = f"{summary} went dark just now — {impact_str}."
            priority = "critical" if severity == "critical" else "high"
            # Degradations keep the 0.5h system_health cooldown (anti-nag).
            cooldown_hours = None
        else:
            title = "All clear"
            message = f"{summary} is back — I'm whole again. That was a brief blip."
            # The all-clear MUST reach David: it closes an alert he already saw.
            # (1) cooldown_hours=0 so it isn't killed by the degradation's own
            #     0.5h system_health cooldown (they fire minutes apart).
            # (2) "high" so it actually delivers instead of being filed as a
            #     silent inbox item (gotcha_attention_queue_priority_push).
            priority = "high"
            cooldown_hours = 0.0

        # Stable topic per subsystem-set so an exact repeat still dedups.
        topic = f"interoception:{kind}:{'_'.join(sorted(subsystems.keys()))}"
        res = await send_notification(
            user_id=user_id,
            title=title,
            message=message,
            priority=priority,
            topic=topic,
            category="system_health",
            source="interoception",
            cooldown_hours=cooldown_hours,
        )
        result["alerts"].append({"kind": kind, "sent": res.get("sent"), "reason": res.get("reason")})
        return bool(res.get("sent"))
    except Exception as e:
        logger.warning(f"[body_sense] failed to send {kind} alert: {e}")
        return False


async def current_self_status(user_id: str = DAVID_USER_ID) -> Dict[str, Any]:
    """What Sara currently feels about her own body — for the greeting/brief.

    Returns {healthy: bool, degraded: [{subsystem, name, impact, severity}]}.
    Reads the persisted interoception state (cheap; no live probing)."""
    try:
        r = await _get_redis()
        state = await _load_state(r)
        try:
            await r.close()
        except Exception:
            pass
        degraded = [
            {
                "subsystem": s,
                "name": _label(s)[0],
                "impact": _label(s)[1],
                "severity": sev,
            }
            for s, sev in state.items()
        ]
        return {"healthy": not degraded, "degraded": degraded}
    except Exception as e:
        logger.debug(f"[body_sense] current_self_status failed: {e}")
        return {"healthy": True, "degraded": []}
