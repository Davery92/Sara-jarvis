"""Judge (SARA_MIND_V2_PLAN Phase 4/§3.6) — ranks pending say_candidates,
decides drop/batch/send_now, and plans bounded prep work.

SHADOW MODE — this session's explicit scope decision: the judge makes and
persists a REAL decision + reasoning for every pending candidate (the
why-chain principle #8 requires this to exist regardless of whether
delivery is wired), and DOES dispatch bounded prep work through the
existing agent_dispatch tiers/hard-block gate (Act-then-speak, §Phase 4 —
prep work has real, bounded value on its own). It does NOT call
`send_notification` for `send_now` candidates: Compose/Review (Phase 2)
don't exist yet, so there is no reviewed, voice-doc-composed message to
send — only the judge's raw candidate summary, which is explicitly NOT
final phrasing (§3.5). A `send_now` decision today means "the judge
believes this is worth telling him," recorded and auditable — not "he was
told." Wiring judge decisions to actual delivery is Phase 2 territory and
needs its own shadow-week validation per the plan's own acceptance
criteria, not a silent side effect of building this file.
"""
import json
import logging
from datetime import timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Same envelope deliberation_gate.py already trusts for auto-execute task
# proposals — prep actions reuse it rather than opening a second unguarded
# path to agent_dispatch. Hard-block categories are never dispatched,
# full stop, regardless of what the judge's LLM call proposes.
_PREP_ALLOWED_CATEGORIES = {"research", "pkg_update", "note_organization", "home_control"}


async def _gather_utterance_history(db, user_id: str, days: int = 14) -> List[Dict[str, Any]]:
    since = local_now() - timedelta(days=days)
    rows = (await db.execute(text("""
        SELECT title, category, sent_at, engaged
        FROM notification_log
        WHERE user_id = :uid AND sent = TRUE AND sent_at >= :since
        ORDER BY sent_at DESC LIMIT 60
    """), {"uid": user_id, "since": since})).fetchall()
    return [
        {
            "title": r.title, "category": r.category,
            "at": r.sent_at.isoformat() if r.sent_at else None,
            "engaged": bool(r.engaged),
        }
        for r in rows
    ]


async def _gather_recent_chat(db, user_id: str, hours: int = 6, limit: int = 30) -> List[Dict[str, Any]]:
    """Last few hours of chat turns (role + a short excerpt) — this is the
    fix for the Phxins-push / BitTitan-nag class (Mind V2 rewire plan,
    Workstream C): a candidate about something David already handled,
    dismissed, postponed, or contradicted in conversation should die in the
    judge, not surface as a stale push.

    conversation_turn.created_at is `timestamp without time zone` storing
    naive UTC (verified against live data) — bind naive UTC bounds
    directly. Do NOT pass this through the ET helpers or `AT TIME ZONE`;
    that would double-shift it (same gotcha class app/core/timezone.py's
    docstring warns about for naive-ET columns, mirrored here for UTC)."""
    from app.core.timezone import naive_utc_now

    since = naive_utc_now() - timedelta(hours=hours)
    rows = (await db.execute(text("""
        SELECT role, content, created_at FROM conversation_turn
        WHERE user_id = :uid AND created_at >= :since
        ORDER BY created_at DESC LIMIT :limit
    """), {"uid": user_id, "since": since, "limit": limit})).fetchall()
    turns = [
        {
            "role": r.role,
            "content": (r.content or "")[:200],
            "at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    turns.reverse()  # chronological for the prompt
    return turns


async def _gather_context(db, user_id: str) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {}
    try:
        from app.services.activity_state_machine import activity_state_machine
        from app.services.interruptibility import compute_interruptibility
        state = activity_state_machine.current
        ctx["activity_state"] = getattr(getattr(state, "state", None), "value", None)
        ctx["interruptibility"] = compute_interruptibility(state).score
    except Exception as e:
        logger.debug(f"[judge] activity/interruptibility unavailable: {e}")

    try:
        from app.services.delivery_policy import sense_sleep_state
        sleep = await sense_sleep_state(db, user_id)
        ctx["asleep"] = sleep.asleep
    except Exception as e:
        logger.debug(f"[judge] sleep state unavailable: {e}")

    # Remaining interrupt allowance — same accounting as unified_notification
    # ._daily_push_budget_available (2/day, excluding urgent/critical and
    # timer/reminder/agent_task rows).
    try:
        count_today = (await db.execute(text("""
            SELECT COUNT(*) FROM notification_log
            WHERE user_id = :uid AND sent = TRUE
              AND priority NOT IN ('urgent', 'critical')
              AND category NOT IN ('timer', 'reminder', 'reminders', 'timers', 'agent_task')
              AND sent_at >= (date_trunc('day', NOW() AT TIME ZONE 'America/New_York')
                              AT TIME ZONE 'America/New_York')
        """), {"uid": user_id})).scalar() or 0
        ctx["remaining_interrupt_allowance"] = max(0, 2 - int(count_today))
    except Exception as e:
        logger.debug(f"[judge] interrupt allowance unavailable: {e}")

    try:
        ctx["recent_chat"] = await _gather_recent_chat(db, user_id)
    except Exception as e:
        logger.debug(f"[judge] recent chat unavailable: {e}")
        ctx["recent_chat"] = []

    return ctx


def _build_prompt(
    candidates: List[Dict[str, Any]],
    brief_text: str,
    interest_text: str,
    utterance_history: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> Tuple[str, str]:
    now_str = local_now().strftime("%A, %B %-d, %Y, %-I:%M %p ET")

    cand_lines = []
    for c in candidates:
        cand_lines.append(
            f"- id={c['id']} kind={c['kind']} value_guess={c.get('value_guess')} "
            f"valid_until={c.get('valid_until')} source={c['source']}\n"
            f"  summary: {c['summary']}"
        )
    cand_block = "\n".join(cand_lines) if cand_lines else "(none)"

    hist_lines = [
        f"- [{h['at'][:16] if h['at'] else '?'}] ({h['category']}) \"{h['title']}\" — "
        f"{'engaged' if h['engaged'] else 'not engaged'}"
        for h in utterance_history[:30]
    ]
    hist_block = "\n".join(hist_lines) if hist_lines else "(no sends in the last 14 days)"

    ctx_bits = []
    if context.get("activity_state"):
        ctx_bits.append(f"activity={context['activity_state']}")
    if context.get("interruptibility") is not None:
        ctx_bits.append(f"interruptibility={context['interruptibility']:.2f}")
    if context.get("asleep") is not None:
        ctx_bits.append(f"asleep={context['asleep']}")
    if context.get("remaining_interrupt_allowance") is not None:
        ctx_bits.append(f"remaining_interrupt_allowance={context['remaining_interrupt_allowance']}")
    ctx_block = ", ".join(ctx_bits) if ctx_bits else "(unknown)"

    recent_chat = context.get("recent_chat") or []
    chat_lines = [
        f"- [{t['at'][:16] if t['at'] else '?'}] {t['role']}: {t['content']}"
        for t in recent_chat
    ]
    chat_block = "\n".join(chat_lines) if chat_lines else "(no chat in the last 6 hours)"

    system_msg = (
        "You are Sara's judge: you decide which candidate facts are worth telling David, "
        "when, and whether prep work should happen first. You do not write the message "
        "itself — a separate compose step (not yet built) owns final phrasing.\n\n"
        "For EVERY candidate listed, decide exactly one of:\n"
        "  - drop: not worth it right now (always include a real reason, not \"low value\")\n"
        "  - batch: worth mentioning, but in a scheduled slot (morning or evening), not now\n"
        "  - send_now: worth interrupting for, right now\n\n"
        "Weigh: the World Brief and Interest Model (does this match what David actually "
        "cares about?), his utterance history (a category/topic he's ignored repeatedly "
        "should raise the bar; one he's engaged with should lower it), and his current "
        "context (never send_now if asleep; interruptibility below ~0.4 should push toward "
        "batch or drop unless the candidate kind is 'alert'; respect the remaining interrupt "
        "allowance — if it's 0, nothing gets send_now except genuine alerts).\n\n"
        "If the recent conversation below shows David has already handled, dismissed, "
        "postponed, or contradicted a candidate's substance, the decision is drop, with the "
        "chat turn (paraphrased) as the reason — regardless of how the candidate otherwise "
        "scores.\n\n"
        "You may also propose bounded prep_actions — small tasks worth doing BEFORE any "
        "message goes out (pull a document, gather context, organize notes). Only propose "
        "these for candidates of kind 'prep', and only in categories research, pkg_update, "
        "note_organization, or home_control — never anything resembling sending an email, "
        "a purchase, or an external message (those are hard-blocked regardless of what you "
        "propose).\n\n"
        "Respond with ONLY valid JSON:\n"
        "{\n"
        '  "decisions": [{"candidate_id": "...", "decision": "drop|batch|send_now", '
        '"batch_slot": "morning|evening (only if decision=batch)", "reason": "..."}],\n'
        '  "prep_actions": [{"candidate_id": "...", "category": "research|pkg_update|'
        'note_organization|home_control", "description": "...", "confidence": 0.8}]\n'
        "}\n"
        "Every candidate_id in the input MUST appear exactly once in decisions."
    )

    user_msg = (
        f"AS OF: {now_str}\n\n"
        f"## Current World Brief\n{brief_text}\n\n"
        f"## Interest Model (what David cares about)\n{interest_text}\n\n"
        f"## Current context\n{ctx_block}\n\n"
        f"## Recent conversation (last 6 hours — has David already handled any of this?)\n{chat_block}\n\n"
        f"## Utterance history (last 14 days, what was said + engagement)\n{hist_block}\n\n"
        f"## Pending candidates ({len(candidates)})\n{cand_block}\n"
    )
    return system_msg, user_msg


def _parse_response(raw: str) -> dict:
    text_ = (raw or "").strip()
    if "```" in text_:
        parts = text_.split("```")
        if len(parts) >= 3:
            inner = parts[1]
            if inner.startswith("json"):
                inner = inner[4:]
            text_ = inner.strip()
        else:
            lines = [l for l in text_.split("\n") if not l.strip().startswith("```")]
            text_ = "\n".join(lines).strip()
    try:
        return json.loads(text_)
    except json.JSONDecodeError:
        pass
    brace_idx = text_.find("{")
    if brace_idx > 0:
        try:
            return json.loads(text_[brace_idx:])
        except json.JSONDecodeError:
            pass
    if brace_idx >= 0:
        last_brace = text_.rfind("}")
        if last_brace > brace_idx:
            try:
                return json.loads(text_[brace_idx:last_brace + 1])
            except json.JSONDecodeError:
                pass
    raise json.JSONDecodeError("No valid JSON found in judge response", text_, 0)


async def _apply_decision(db, user_id: str, candidate_id: str, decision: str, reason: str, batch_slot: str = None) -> None:
    from app.services.candidate_states import JUDGE_DECISION_TO_STATUS

    status = JUDGE_DECISION_TO_STATUS.get(decision)
    if not status:
        raise ValueError(f"unknown judge decision: {decision!r}")

    full_reason = reason or ""
    if decision == "batch" and batch_slot:
        full_reason = f"[slot={batch_slot}] {full_reason}"

    await db.execute(text("""
        UPDATE say_candidate
        SET status = :status, judge_reason = :reason
        WHERE id = :id AND user_id = :uid AND status = 'pending'
    """), {"status": status.value, "reason": full_reason[:2000], "id": candidate_id, "uid": user_id})
    await db.commit()


async def _dispatch_prep_action(db, user_id: str, candidate_id: str, category: str, description: str, confidence: float) -> None:
    if category not in _PREP_ALLOWED_CATEGORIES:
        logger.warning(f"[judge] prep action rejected — category {category!r} not in allowed set")
        return
    if confidence < 0.6:
        logger.info(f"[judge] prep action skipped — confidence {confidence} below threshold")
        return

    from app.services.deliberation_gate import _auto_execute_should_skip
    from app.services.deliberation import TaskProposal

    proposal = TaskProposal(description=description, category=category, confidence=confidence, reason="judge prep")
    skip_reason = await _auto_execute_should_skip(user_id, category, proposal)
    if skip_reason:
        logger.info(f"[judge] prep action skipped ({skip_reason}): {description[:80]}")
        return

    try:
        from app.services.agent_dispatch import agent_dispatch_service
        from app.db.session import SessionLocal

        sync_db = SessionLocal()
        try:
            result = await agent_dispatch_service.dispatch_task(
                db=sync_db, user_id=user_id, task_description=description,
                mode="auto", notify_on_complete=False,
            )
        finally:
            sync_db.close()

        # Attach the dispatch result to the candidate's evidence trail —
        # "results attach to the candidate" (§3.6).
        await db.execute(text("""
            UPDATE say_candidate
            SET evidence = evidence || CAST(:prep AS jsonb)
            WHERE id = :id AND user_id = :uid
        """), {
            "id": candidate_id, "uid": user_id,
            "prep": json.dumps([{"prep_dispatched": True, "task_id": result.get("task_id"), "category": category}]),
        })
        await db.commit()
    except Exception as e:
        logger.warning(f"[judge] prep dispatch failed for candidate {candidate_id}: {e}")


async def run_judge(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    from app.services.say_candidate import purge_expired, pending_candidates
    from app.services.world_brief import get_rendered_brief
    from app.services.interest_model import get_rendered_interest_model
    from app.db.session import get_async_session_factory

    factory = get_async_session_factory()

    async with factory() as db:
        purged = await purge_expired(db, user_id)
        candidates = await pending_candidates(db, user_id)

    if not candidates:
        return {"skipped": "no_candidates", "purged": purged}

    async with factory() as db:
        brief_text = await get_rendered_brief(db, user_id)
        interest_text = await get_rendered_interest_model(db, user_id)
        utterance_history = await _gather_utterance_history(db, user_id)
        context = await _gather_context(db, user_id)

    system_msg, user_msg = _build_prompt(candidates, brief_text, interest_text, utterance_history, context)

    try:
        from app.core.llm import get_background_llm_client
        client = get_background_llm_client()
        response = await client.chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=1500,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = response["choices"][0]["message"].get("content", "") if isinstance(response, dict) else str(response)
    except Exception as e:
        logger.error(f"[judge] LLM call failed: {e}")
        return {"error": str(e), "purged": purged}

    try:
        parsed = _parse_response(raw)
    except Exception as e:
        logger.warning(f"[judge] parse failed: {e}. Raw: {raw[:200]}")
        return {"error": f"parse_failed: {e}", "purged": purged}

    known_ids = {c["id"] for c in candidates}
    stats = {"drop": 0, "batch": 0, "send_now": 0, "unknown_id": 0, "prep_actions": 0, "purged": purged}

    async with factory() as db:
        for d in parsed.get("decisions", []) or []:
            cid = d.get("candidate_id")
            decision = d.get("decision")
            if cid not in known_ids:
                stats["unknown_id"] += 1
                continue
            try:
                await _apply_decision(db, user_id, cid, decision, d.get("reason", ""), d.get("batch_slot"))
                stats[decision] = stats.get(decision, 0) + 1
            except Exception as e:
                logger.warning(f"[judge] decision apply failed for {cid}: {e}")

        for p in parsed.get("prep_actions", []) or []:
            cid = p.get("candidate_id")
            if cid not in known_ids:
                continue
            try:
                await _dispatch_prep_action(
                    db, user_id, cid, p.get("category", ""), p.get("description", ""),
                    float(p.get("confidence", 0.0)),
                )
                stats["prep_actions"] += 1
            except Exception as e:
                logger.warning(f"[judge] prep action failed for {cid}: {e}")

    logger.info(f"[judge] cycle complete: {stats}")
    return stats
