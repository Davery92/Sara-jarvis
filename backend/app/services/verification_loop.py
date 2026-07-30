"""
Verification loop (Arc 5.2) — "the verification loop retires unverified
facts one natural question at a time (capped, anti-nag)."

The "ask" half only. Picks the single highest-priority unverified fact
(a PKG node flagged `needs_review` by validate_against_recent's
contradiction detection, or failing that the lowest-confidence
observed-tier PKG fact) and mints ONE `say_candidate` through the
existing judge -> compose -> review -> send pipeline — no new delivery
mechanism, no new store. Capped at one per day via the same
dedupe_key + daily-check discipline `curiosity.py`'s `pursued_today()`
already established for this exact "don't nag" shape.

The "retire" half is NOT built here. When David answers naturally in
conversation, two existing, real primitives already cover part of it:
`life_facts.detect_and_apply_correction()` (regex-based, already scans
every chat message for a stated correction — a natural answer to a
life_fact verification question already lands there with no new code)
and `personal_knowledge_graph.PersonalKnowledgeGraph.mark_reviewed()`
(clears needs_review + updates confidence, callable, but nothing wires
a conversational reply to it automatically yet). Full round-trip —
Sara asks, parses which specific answer goes with which specific
question, calls mark_reviewed automatically — is real, scoped-out
future work, not silently assumed done.
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


async def verified_today(db, user_id: str = DEFAULT_USER_ID) -> bool:
    """Daily budget check — same shape as curiosity.pursued_today()."""
    row = (await db.execute(text("""
        SELECT 1 FROM say_candidate
        WHERE user_id = :uid AND source = 'verification'
          AND created_at::date = CURRENT_DATE
        LIMIT 1
    """), {"uid": user_id})).first()
    return row is not None


def _pick_unverified_fact() -> Optional[Dict[str, Any]]:
    """Highest-priority unverified fact: a PKG node genuinely flagged
    needs_review (real contradiction evidence, not just "not very
    confident yet") beats a merely-low-confidence one — a flagged fact
    means the system has actively noticed something conflicting, which
    is a stronger signal than "hasn't come up enough to be sure."""
    from app.services.personal_knowledge_graph import personal_kg

    flagged = personal_kg.get_needs_review()
    if flagged:
        top = flagged[0]  # already ordered by review_flagged_at DESC
        return {
            "pkg_id": top.get("pkg_id"),
            "fact_summary": top.get("fact_summary"),
            "reason": top.get("review_reason") or "conflicting evidence",
            "evidence": top.get("review_evidence") or "",
        }

    from app.services.confidence_ladder import tier_from_confidence
    from app.services.memory_recall import _fact_text

    observed_tier = [
        item for item in personal_kg.browse(limit=100)
        if tier_from_confidence(item.get("confidence", 0)) == "observed"
    ]
    if not observed_tier:
        return None
    least_confident = min(observed_tier, key=lambda item: item.get("confidence", 0))
    summary = _fact_text(least_confident)
    if not summary:
        return None
    return {
        "pkg_id": least_confident.get("pkg_id"),
        "fact_summary": summary,
        "reason": "low confidence, never confirmed",
        "evidence": "",
    }


async def _generate_question(fact: Dict[str, Any]) -> Optional[str]:
    """One natural, specific question about the fact — not a generic
    'is this still accurate?' template."""
    from app.core.llm import llm_client

    prompt = f'''You're Sara. You have a fact about David you're not fully sure of:

"{fact['fact_summary']}"

Why you're unsure: {fact['reason']}
{f"Evidence: {fact['evidence']}" if fact['evidence'] else ""}

Write ONE short, natural, specific question you could ask David in conversation to verify or correct this — not "is this still accurate?" (too generic), something that sounds like you actually noticed something and are curious. One sentence.'''

    try:
        response = await llm_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            timeout=60.0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        if response and "choices" in response:
            content = response["choices"][0]["message"]["content"]
            return content.strip() if content else None
    except Exception as e:
        logger.warning(f"[verification_loop] question generation failed: {e}")
    return None


async def generate_verification_candidate(db, user_id: str = DEFAULT_USER_ID) -> Optional[str]:
    """Dreaming-cycle entry point. Returns the minted question text, or
    None if there was nothing to verify / budget already spent today /
    generation failed."""
    if await verified_today(db, user_id):
        return None

    fact = _pick_unverified_fact()
    if not fact or not fact.get("fact_summary"):
        return None

    question = await _generate_question(fact)
    if not question:
        return None

    from app.services.say_candidate import create_candidate
    await create_candidate(
        db, user_id, source="verification", kind="inform",
        summary=question,
        evidence=[fact["fact_summary"], fact["reason"]],
        dedupe_key=f"verify:pkg:{fact['pkg_id']}",
    )
    return question
