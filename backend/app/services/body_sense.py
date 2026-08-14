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
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DAVID_USER_ID = get_owner_id()

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
    """(friendly_name, impact) for a subsystem key. Handles host:<name> and
    llm_chat:<provider> (2026-07-31: closes "can't feel Claude failing" —
    see record_chat_provider_failure below)."""
    if subsystem.startswith("host:"):
        name = subsystem.split(":", 1)[1]
        return (f"the {name} host", f"I've lost access to {name}")
    if subsystem.startswith("llm_chat:"):
        provider = subsystem.split(":", 1)[1]
        return (f"my presence-chat model ({provider})", "real-time conversation is down — David sees an error instead of a reply")
    return _SUBSYSTEM_LABEL.get(subsystem, (subsystem, "a part of me is degraded"))


async def _get_redis():
    from app.core.redis import get_redis
    return await get_redis()


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


# ─── Chat-provider degradation (2026-07-31) ──────────────────────────────
#
# `reflect()` above is heartbeat-driven: a periodic report, diffed tick over
# tick. It can't be reused as-is for a chat-path failure that needs to be
# felt the instant it happens, not on the next 5-minute tick — and folding
# an ad-hoc key into `_STATE_KEY` would break `reflect()`'s own diffing: it
# rebuilds that dict from scratch every tick from only 3 sources (heartbeat
# checks, daemon, hosts), so any key it doesn't itself track would compute
# as "recovered" on the very next tick regardless of whether the chat
# provider actually recovered. Kept fully separate — same event/alert shape
# (`_emit_and_alert`, unchanged), a second, independent state key, no
# interaction with the report-diffing path at all.
#
# Closes the "she can't feel Claude failing" residue: presence chat
# (`/chat/stream`'s Anthropic dispatch) runs outside Celery entirely, so
# the task_failure→ledger→self-slice path the deep-deliberation fix wired
# up (2026-07-31, same day) never sees it — this is that same shape of
# signal for the one real path it doesn't cover.
_CHAT_STATE_KEY = "system:interoception_chat_state"


async def record_chat_provider_failure(provider: str, error_class: str, detail: str = "") -> bool:
    """Call from a chat provider's own dispatch error handler (e.g.
    `_anthropic_chat_request`'s `except httpx.HTTPError` branch) — a
    genuine 4xx/5xx or connection failure talking to the provider, not a
    downstream bug in Sara's own response handling. Best-effort, fires on
    state transition only (repeated failures while already down are a
    no-op past the first). Returns True iff this was a new transition."""
    key = f"llm_chat:{provider}"
    try:
        r = await _get_redis()
        state = await r.hgetall(_CHAT_STATE_KEY)
        was_down = key in (state or {})
        await r.hset(_CHAT_STATE_KEY, key, json.dumps({
            "severity": "error", "error_class": error_class, "detail": detail[:300],
        }))
        if not was_down:
            result: Dict[str, Any] = {"events": [], "alerts": []}
            delivered = await _emit_and_alert(
                user_id=DAVID_USER_ID, kind="degraded",
                subsystems={key: "error"}, severity="error", result=result,
            )
            if delivered:
                await _mark_announced(r, [key])
            logger.info(f"[body_sense] chat provider degraded: {key} ({error_class})")
        return not was_down
    except Exception as e:
        logger.debug(f"[body_sense] record_chat_provider_failure failed: {e}")
        return False


async def record_chat_provider_recovery(provider: str) -> bool:
    """Call from the same dispatch path on a successful response — cheap
    (one Redis read) and a no-op unless this provider was actually marked
    down, matching `reflect()`'s own "only close what was announced"
    discipline. Returns True iff this cleared a real degradation."""
    key = f"llm_chat:{provider}"
    try:
        r = await _get_redis()
        state = await r.hgetall(_CHAT_STATE_KEY)
        if key not in (state or {}):
            return False
        await r.hdel(_CHAT_STATE_KEY, key)
        announced = await _load_announced(r)
        to_close = key in announced
        result: Dict[str, Any] = {"events": [], "alerts": []}
        await _emit_and_alert(
            user_id=DAVID_USER_ID, kind="recovered",
            subsystems={key: "error"}, severity="normal", result=result,
            notify=to_close,
        )
        if to_close:
            await _clear_announced(r, [key])
        logger.info(f"[body_sense] chat provider recovered: {key}")
        return True
    except Exception as e:
        logger.debug(f"[body_sense] record_chat_provider_recovery failed: {e}")
        return False


async def current_chat_provider_status() -> Dict[str, Any]:
    """Same shape as `current_self_status()` (cheap, no live probing) —
    for `body_state_projection` to fold into the canonical self slice
    alongside the heartbeat-driven degradations."""
    try:
        r = await _get_redis()
        raw = await r.hgetall(_CHAT_STATE_KEY)
        degraded = []
        for key, payload in (raw or {}).items():
            try:
                entry = json.loads(payload)
            except Exception:
                entry = {"severity": "error"}
            degraded.append({
                "subsystem": key,
                "name": _label(key)[0],
                "impact": _label(key)[1],
                "severity": entry.get("severity", "error"),
                "error_class": entry.get("error_class"),
            })
        return {"healthy": not degraded, "degraded": degraded}
    except Exception as e:
        logger.debug(f"[body_sense] current_chat_provider_status failed: {e}")
        return {"healthy": True, "degraded": []}
