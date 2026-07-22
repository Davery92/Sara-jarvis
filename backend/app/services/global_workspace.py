"""The Global Workspace (§3.1) — what Sara is holding in mind right now.

One small, always-current, shared structure with ~7 slots:
  1. active conversation threads + open questions
  2. open loops (followups, promises, unanswered Sara-questions)
  3. today's predictions + status (§3.2)
  4. current concern level + what's driving it
  5. in-flight autonomous work (dispatches, research)
  6. today's plan skeleton (calendar / anticipation)
  7. current David-state (location, activity, availability, readiness)

The audit's key lesson: earlier attempts (`working_memory_threads`,
`working_memory_actions`) failed because **nothing was forced to read them.**
So this is deliberately a *derived read model* over data that already exists —
it can't drift out of sync, and every consumer (chat "anything I should know?",
deliberation, the delivery policy, the webapp workspace strip §7.1) reads the
same assembled view. Bounded (≤7 per slot, most-recent/most-salient first).
"""
import logging
from typing import Dict, Any, List, Optional

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
_SLOT_CAP = 7


async def _safe_rollback(db):
    """A caught query error inside a transaction poisons the session for every
    later query. Roll back so the next slot starts clean (all reads here are
    side-effect-free, so rollback loses nothing)."""
    try:
        await db.rollback()
    except Exception:
        pass


async def _open_loops(db, user_id: str) -> List[Dict[str, Any]]:
    loops = []
    try:
        rows = (await db.execute(text("""
            SELECT topic, status, last_mentioned_at
            FROM followup_thread
            WHERE user_id = :u AND status = 'open'
            ORDER BY last_mentioned_at DESC NULLS LAST
            LIMIT :cap
        """), {"u": user_id, "cap": _SLOT_CAP})).fetchall()
        for r in rows:
            loops.append({"topic": r.topic, "kind": "followup"})
    except Exception as e:
        logger.debug(f"open_loops skipped: {e}")
        await _safe_rollback(db)
    return loops


async def _todays_predictions(db, user_id: str) -> Dict[str, Any]:
    try:
        rows = (await db.execute(text("""
            SELECT outcome, COUNT(*) FROM prediction
            WHERE user_id = :u AND created_at >= NOW() - INTERVAL '20 hours'
            GROUP BY outcome
        """), {"u": user_id})).fetchall()
        counts = {r[0]: r[1] for r in rows}
        sample = (await db.execute(text("""
            SELECT statement, outcome FROM prediction
            WHERE user_id = :u AND created_at >= NOW() - INTERVAL '20 hours'
              AND outcome IN ('violated','pending')
            ORDER BY confidence DESC LIMIT :cap
        """), {"u": user_id, "cap": _SLOT_CAP})).fetchall()
        return {
            "confirmed": counts.get("confirmed", 0),
            "violated": counts.get("violated", 0),
            "pending": counts.get("pending", 0),
            "notable": [{"what": s.statement, "status": s.outcome} for s in sample],
        }
    except Exception as e:
        logger.debug(f"predictions slot skipped: {e}")
        await _safe_rollback(db)
        return {}


async def _inflight_work(db, user_id: str) -> List[Dict[str, Any]]:
    work = []
    try:
        rows = (await db.execute(text("""
            SELECT task_type, status FROM background_task
            WHERE user_id = :u AND status IN ('running', 'queued', 'pending', 'processing')
            ORDER BY created_at DESC LIMIT :cap
        """), {"u": user_id, "cap": _SLOT_CAP})).fetchall()
        for r in rows:
            work.append({"kind": r.task_type or "task", "status": r.status})
    except Exception as e:
        logger.debug(f"inflight work skipped: {e}")
        await _safe_rollback(db)
    return work


async def _todays_plan(db, user_id: str) -> List[Dict[str, Any]]:
    plan = []
    try:
        rows = (await db.execute(text("""
            SELECT title, start_time FROM calendar_event
            WHERE user_id = :u
              AND start_time >= NOW() AND start_time < NOW() + INTERVAL '18 hours'
              AND COALESCE(all_day, FALSE) = FALSE
            ORDER BY start_time ASC LIMIT :cap
        """), {"u": user_id, "cap": _SLOT_CAP})).fetchall()
        for r in rows:
            plan.append({"title": r.title,
                         "at": r.start_time.isoformat() if r.start_time else None})
    except Exception as e:
        logger.debug(f"plan slot skipped: {e}")
        await _safe_rollback(db)
    return plan


async def _david_state(db, user_id: str) -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    try:
        from app.services.delivery_policy import sense_sleep_state
        sleep = await sense_sleep_state(db, user_id)
        state["asleep"] = sleep.asleep
        state["sleep_source"] = sleep.source
    except Exception as e:
        logger.debug(f"david_state sleep skipped: {e}")
        await _safe_rollback(db)
    # Readiness (most recent). Lives in morning_readiness.score (young table).
    try:
        r = (await db.execute(text("""
            SELECT score FROM morning_readiness
            WHERE user_id = :u ORDER BY created_at DESC LIMIT 1
        """), {"u": user_id})).first()
        if r and r[0] is not None:
            state["readiness"] = float(r[0])
    except Exception:
        await _safe_rollback(db)
    return state


async def _concern(db, user_id: str) -> Dict[str, Any]:
    """Current concern level from the self-model's health + emotional tone."""
    concern = {"level": "calm", "drivers": []}
    try:
        from app.services.self_model import _health
        h = await _health(db, user_id)
        if not h["ok"]:
            errs = [i for i in h["issues"] if i.get("severity") == "error"]
            concern["level"] = "concerned" if errs else "watchful"
            concern["drivers"] = [i["what"] for i in h["issues"][:3]]
    except Exception as e:
        logger.debug(f"concern slot skipped: {e}")
        await _safe_rollback(db)
    return concern


async def build_workspace(db, user_id: str = _DAVID) -> Dict[str, Any]:
    """Assemble the full workspace (all 7 slots) from live data. Read model."""
    return {
        "generated_at": local_now().isoformat(),
        "open_loops": await _open_loops(db, user_id),
        "predictions_today": await _todays_predictions(db, user_id),
        "concern": await _concern(db, user_id),
        "inflight_work": await _inflight_work(db, user_id),
        "todays_plan": await _todays_plan(db, user_id),
        "david_state": await _david_state(db, user_id),
    }


def format_for_chat(ws: Dict[str, Any]) -> Optional[str]:
    """Render the workspace as a compact system-prompt block (§3.1 enforcement).

    This is what makes chat-Sara genuinely share the background mind: she reads
    her own current working memory before responding, so "anything I should
    know?" and re-entry both draw on the same live state the daemon writes."""
    lines: List[str] = []

    ds = ws.get("david_state") or {}
    if ds:
        bits = []
        if "asleep" in ds:
            bits.append("asleep" if ds["asleep"] else "awake")
        if ds.get("readiness") is not None:
            bits.append(f"readiness {ds['readiness']:.0f}")
        if bits:
            lines.append(f"- David is currently: {', '.join(bits)}.")

    preds = ws.get("predictions_today") or {}
    if preds.get("violated"):
        notable = [n["what"] for n in preds.get("notable", []) if n.get("status") == "violated"][:2]
        detail = f" ({'; '.join(notable)})" if notable else ""
        lines.append(f"- {preds['violated']} of today's predictions were violated{detail} — "
                     f"something is off from the usual pattern.")

    plan = ws.get("todays_plan") or []
    if plan:
        lines.append(f"- Next on the calendar: {plan[0]['title']}"
                     + (f" (+{len(plan) - 1} more today)" if len(plan) > 1 else "") + ".")

    loops = ws.get("open_loops") or []
    if loops:
        lines.append(f"- Open loops with people: {len(loops)} "
                     f"(e.g. {loops[0]['topic']}).")

    work = ws.get("inflight_work") or []
    if work:
        kinds = ", ".join(sorted({w["kind"] for w in work}))
        lines.append(f"- I'm working on {len(work)} thing(s) in the background: {kinds}.")

    concern = ws.get("concern") or {}
    if concern.get("level") and concern["level"] != "calm" and concern.get("drivers"):
        lines.append(f"- On my mind ({concern['level']}): {concern['drivers'][0]}.")

    if not lines:
        return None
    return ("\n\n## What I'm Holding In Mind Right Now (my working memory)\n"
            "This is my live internal state — draw on it naturally; don't recite it.\n"
            + "\n".join(lines))


async def anything_i_should_know(db, user_id: str = _DAVID) -> str:
    """Chat-ready synthesis of the workspace — the §3.1 scenario answer."""
    ws = await build_workspace(db, user_id)
    parts: List[str] = []

    preds = ws.get("predictions_today") or {}
    if preds.get("violated"):
        notable = [n["what"] for n in preds.get("notable", []) if n["status"] == "violated"][:2]
        if notable:
            parts.append("Something's off from the usual: " + "; ".join(notable) + ".")

    plan = ws.get("todays_plan") or []
    if plan:
        parts.append(f"Next up: {plan[0]['title']}.")

    loops = ws.get("open_loops") or []
    if loops:
        parts.append(f"{len(loops)} open loop{'s' if len(loops) != 1 else ''} "
                     f"(e.g. {loops[0]['topic']}).")

    work = ws.get("inflight_work") or []
    if work:
        parts.append(f"{len(work)} thing{'s' if len(work) != 1 else ''} I'm working on in the background.")

    concern = ws.get("concern") or {}
    if concern.get("level") != "calm" and concern.get("drivers"):
        parts.append("On my mind: " + concern["drivers"][0] + ".")

    if not parts:
        return "Nothing pressing — quiet and on-track right now."
    return " ".join(parts)
