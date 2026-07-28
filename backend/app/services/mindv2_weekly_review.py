"""Weekly review (SARA_MIND_V2_PLAN §6 Phase 4) — a new, Mind-V2-specific
weekly synthesis. Deliberately separate from the existing
`learning_digest.send_weekly_digest` (theta/attention-policy learning,
Sunday ~7pm) and `interoception.weekly_self_audit` (system health, Sunday
6:30pm) — neither of those owns "what David cares about" or "how is the
shadow judge doing", and conflating them would blur three genuinely
different reviews into one unfocused one.

Sections (§3.9/§6 Phase 4):
  1. Open commitments — surfaced so nothing silently rots past 30 days.
  2. Interest-model diff proposals — entity-level engagement vs. the
     current top_of_mind ranking (proposals only; David approves in chat/
     settings, nothing here auto-applies rank changes yet).
  3. Utterance self-eval — engagement by category + the shadow judge's
     decision mix (drop/batch/send_now), so the still-dark Judge/Compose
     path is observable before it ever gates real delivery.
  4. Training-week synthesis (§3.11) — volume, PRs, adherence, recovery
     trend, feeding both this review and (eventually) the interest-model
     diff for phase changes (cut vs. bulk shifts what's welcome to say).

Output: one `sara_journal` entry (entry_type='weekly_review') — reflective,
never a push, matching the existing weekly-digest convention.
"""
import logging
from datetime import timedelta
from typing import Any, Dict, List

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


async def _open_commitments_section(db, user_id: str) -> str:
    from app.services.commitment_service import list_open_commitments

    commitments = await list_open_commitments(db, user_id)
    if not commitments:
        return "No open commitments."

    now = local_now()
    lines = []
    for c in commitments:
        created = c.get("created_at")
        age_note = ""
        if created:
            try:
                from datetime import datetime as _dt
                age_days = (now - _dt.fromisoformat(created)).days
                if age_days >= 30:
                    age_note = f" — {age_days}d old, review whether this should close or drop"
                elif age_days >= 7:
                    age_note = f" ({age_days}d old)"
            except Exception:
                pass
        lines.append(f"- {c['text']}{age_note}")
    return "\n".join(lines)


async def _interest_model_diff_section(db, user_id: str) -> str:
    """Entity-level engagement this week vs. current top_of_mind — proposals
    only, nothing auto-applies. Cheap heuristic: does any topic phrase in
    the current top_of_mind list appear in a notification title/category
    that got engaged this week, or NOT appear in any engaged item at all?"""
    from app.services.interest_model import get_interest_model

    state = await get_interest_model(db, user_id)
    top = state["content"].get("top_of_mind") or []
    if not top:
        return "Interest model has no top_of_mind entries to diff against yet."

    since = local_now() - timedelta(days=7)
    rows = (await db.execute(text("""
        SELECT title, category, engaged FROM notification_log
        WHERE user_id = :uid AND sent = TRUE AND sent_at >= :since
    """), {"uid": user_id, "since": since})).fetchall()

    engaged_text = " ".join((r.title or "").lower() for r in rows if r.engaged)

    proposals = []
    for item in top:
        text_ = (item.get("text") if isinstance(item, dict) else str(item)) or ""
        # First significant word as a crude topic key (e.g. "Risk Ninja —..." -> "risk")
        key = text_.split()[0].lower().strip(",.—-") if text_.split() else ""
        if key and len(key) > 3 and key not in engaged_text:
            proposals.append(f"- No engagement this week on \"{text_[:60]}\" — still relevant, or should it drop in rank?")

    if not proposals:
        return "No rank-shift proposals this week — engagement matches the current ranking."
    return "\n".join(proposals[:5])


async def _utterance_self_eval_section(db, user_id: str) -> str:
    since = local_now() - timedelta(days=7)

    eng_rows = (await db.execute(text("""
        SELECT category, COUNT(*)::int AS sent, COUNT(*) FILTER (WHERE engaged)::int AS engaged
        FROM notification_log
        WHERE user_id = :uid AND sent = TRUE AND sent_at >= :since
        GROUP BY category ORDER BY sent DESC
    """), {"uid": user_id, "since": since})).fetchall()
    eng_lines = [
        f"- {r.category}: {r.engaged}/{r.sent} engaged ({round(r.engaged / r.sent * 100) if r.sent else 0}%)"
        for r in eng_rows
    ]

    judge_rows = (await db.execute(text("""
        SELECT status, COUNT(*)::int AS n FROM say_candidate
        WHERE user_id = :uid AND created_at >= :since
        GROUP BY status
    """), {"uid": user_id, "since": since})).fetchall()
    judge_lines = [f"- {r.status}: {r.n}" for r in judge_rows]

    parts = []
    if eng_lines:
        parts.append("Sent-message engagement by category:\n" + "\n".join(eng_lines))
    if judge_lines:
        parts.append("Shadow judge decision mix (not yet gating real delivery):\n" + "\n".join(judge_lines))
    return "\n\n".join(parts) if parts else "No sends or judge activity this week."


async def _training_week_synthesis_section(db, user_id: str) -> str:
    since_date = (local_now() - timedelta(days=7)).date()

    day_rows = (await db.execute(text("""
        SELECT COUNT(DISTINCT session_date)::int FROM workout_log
        WHERE user_id = :uid AND session_date >= :since AND voided_at IS NULL
    """), {"uid": user_id, "since": since_date})).scalar() or 0

    set_count = (await db.execute(text("""
        SELECT COUNT(*)::int FROM workout_log
        WHERE user_id = :uid AND session_date >= :since
          AND voided_at IS NULL AND set_kind = 'working'
    """), {"uid": user_id, "since": since_date})).scalar() or 0

    pr_count = (await db.execute(text("""
        SELECT COUNT(*)::int FROM workout_log
        WHERE user_id = :uid AND session_date >= :since
          AND voided_at IS NULL AND is_pr = TRUE
    """), {"uid": user_id, "since": since_date})).scalar() or 0

    readiness_rows = (await db.execute(text("""
        SELECT AVG(score)::float FROM morning_readiness
        WHERE user_id = :uid AND created_at >= :since
    """), {"uid": user_id, "since": since_date})).scalar()

    bits = [f"{day_rows} training day(s) logged", f"{set_count} working set(s)"]
    if pr_count:
        bits.append(f"{pr_count} PR(s)")
    if readiness_rows is not None:
        bits.append(f"avg readiness {readiness_rows:.0f}")
    return "- " + ", ".join(bits) + "."


async def build_weekly_review(user_id: str = DEFAULT_USER_ID) -> Dict[str, str]:
    from app.db.session import get_async_session_factory

    factory = get_async_session_factory()
    async with factory() as db:
        sections = {
            "open_commitments": await _open_commitments_section(db, user_id),
            "interest_model_diff": await _interest_model_diff_section(db, user_id),
            "utterance_self_eval": await _utterance_self_eval_section(db, user_id),
            "training_week": await _training_week_synthesis_section(db, user_id),
        }
    return sections


def _render_note(sections: Dict[str, str]) -> str:
    return (
        "## Weekly review\n\n"
        f"**Open commitments**\n{sections['open_commitments']}\n\n"
        f"**Interest model — proposed diffs**\n{sections['interest_model_diff']}\n\n"
        f"**What I said this week**\n{sections['utterance_self_eval']}\n\n"
        f"**Training week**\n{sections['training_week']}"
    )


async def run_weekly_review(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    sections = await build_weekly_review(user_id)
    note = _render_note(sections)

    from app.db.session import get_async_session_factory
    import uuid as _uuid

    factory = get_async_session_factory()
    async with factory() as db:
        await db.execute(text("""
            INSERT INTO sara_journal (id, user_id, entry_type, content, created_at)
            VALUES (:id, :uid, 'weekly_review', :content, NOW())
        """), {"id": str(_uuid.uuid4()), "uid": user_id, "content": note[:4000]})
        await db.commit()

    logger.info(f"[mindv2_weekly_review] wrote weekly review journal entry ({len(note)} chars)")
    return {"written": True, "length": len(note)}
