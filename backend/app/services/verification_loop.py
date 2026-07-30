"""
Verification loop (Arc 5.2) — "the verification loop retires unverified
facts one natural question at a time (capped, anti-nag)."

**Ask half**: picks the single highest-priority unverified fact (a PKG
node flagged `needs_review` by validate_against_recent's contradiction
detection, or failing that the lowest-confidence observed-tier PKG
fact) and mints ONE `say_candidate` through the existing judge ->
compose -> review -> send pipeline — no new delivery mechanism, no new
store. Capped at one per day via the same dedupe_key + daily-check
discipline `curiosity.py`'s `pursued_today()` already established for
this exact "don't nag" shape.

**Retire half**: `check_and_apply_verification_answer()`, called
synchronously from the chat pipeline the same way and same place
`life_facts.detect_and_apply_correction()` already is (before the
reply, on every incoming message) — finds the most recent verification
candidate that was actually DELIVERED (composed_utterance.delivered_at
IS NOT NULL, not just judged/composed) within the last 3 days, and
whose fact is still unresolved (needs_review still true — this is also
what makes the whole thing idempotent: once mark_reviewed clears the
flag, there is nothing left to re-match, no separate "consumed" flag
needed). One cheap LLM classification call decides CONFIRMED /
CORRECTED / UNCLEAR; CONFIRMED graduates confidence, CORRECTED demotes
it (retires it from being surfaced as a decent-confidence fact again),
UNCLEAR touches nothing and leaves it open for a later reply. Runs
silently — Sara's actual reply to David is not altered by this; the
whole point of asking naturally was to get the information, not to
narrate the bookkeeping back at him.

Not built, still real scope: this only covers PKG facts (matching the
ask half, which is PKG-only), not life_fact verification questions —
life_fact answers already flow through the pre-existing
`detect_and_apply_correction()` for free since it scans every message
already, so a life_fact-specific retire path isn't a gap, just a
different existing mechanism serving the same role.
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


async def _find_pending_verification(db, user_id: str) -> Optional[Dict[str, Any]]:
    """The most recent verification question actually delivered to
    David (not just judged/composed — delivered_at is set by the real
    send path) in the last 3 days, whose fact hasn't been resolved yet.
    That last check is also what makes this safe to call on every
    message with no separate "already answered" flag: once the fact's
    needs_review clears or it graduates out of observed-tier, this
    stops matching on its own — covers both sources _pick_unverified_
    fact can produce (needs_review-flagged, or merely observed-tier),
    not just the first one."""
    row = (await db.execute(text("""
        SELECT sc.topic_entities[1] AS dedupe_key,
               COALESCE(cu.final_text, sc.summary) AS question_text
        FROM say_candidate sc
        JOIN composed_utterance cu ON cu.id = sc.utterance_id
        WHERE sc.user_id = :uid AND sc.source = 'verification'
          AND cu.delivered_at IS NOT NULL
          AND cu.delivered_at > NOW() - INTERVAL '3 days'
        ORDER BY cu.delivered_at DESC
        LIMIT 1
    """), {"uid": user_id})).first()
    if not row or not row.dedupe_key or not row.dedupe_key.startswith("verify:pkg:"):
        return None
    pkg_id = row.dedupe_key[len("verify:pkg:"):]

    from app.services.personal_knowledge_graph import personal_kg
    from app.services.confidence_ladder import tier_from_confidence
    status = personal_kg.get_node_status(pkg_id)
    if not status:
        return None  # already retired (deleted) by a prior reply
    if not status["needs_review"] and tier_from_confidence(status["confidence"]) != "observed":
        return None  # already resolved

    return {"pkg_id": pkg_id, "question_text": row.question_text}


async def _classify_answer(question: str, reply: str) -> str:
    """CONFIRMED / CORRECTED / UNCLEAR — one cheap LLM call, only made
    when a pending verification genuinely exists (rare: capped at
    1/day, 3-day window), not on every message."""
    from app.core.llm import llm_client

    prompt = f'''Sara asked David this question:
"{question}"

David just replied:
"{reply}"

Does David's reply answer Sara's question? Respond with EXACTLY one word:
CONFIRMED — he confirms the thing Sara asked about is accurate
CORRECTED — he says it's wrong / different / outdated
UNCLEAR — his reply doesn't actually address the question'''

    try:
        response = await llm_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            timeout=30.0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        if response and "choices" in response:
            content = (response["choices"][0]["message"]["content"] or "").strip().upper()
            for label in ("CONFIRMED", "CORRECTED", "UNCLEAR"):
                if label in content:
                    return label
    except Exception as e:
        logger.warning(f"[verification_loop] answer classification failed: {e}")
    return "UNCLEAR"


async def check_and_apply_verification_answer(
    db, user_id: str = DEFAULT_USER_ID, message: str = ""
) -> Optional[Dict[str, Any]]:
    """Chat-pipeline entry point — call this the same place and the
    same way life_facts.detect_and_apply_correction() is already
    called, before the reply, on every incoming message. Cheap no-op
    (one query, no LLM call) on the overwhelming majority of messages
    where no verification is pending."""
    if not message or not message.strip():
        return None

    pending = await _find_pending_verification(db, user_id)
    if not pending:
        return None

    verdict = await _classify_answer(pending["question_text"], message)
    if verdict == "UNCLEAR":
        return None

    from app.services.personal_knowledge_graph import personal_kg
    if verdict == "CONFIRMED":
        # Graduate: clear needs_review (if it was flagged) and bump
        # confidence — mark_reviewed is the existing, correct primitive
        # for "David reviewed this and it's right."
        status = personal_kg.get_node_status(pending["pkg_id"])
        current_conf = status["confidence"] if status else 0.5
        personal_kg.mark_reviewed(pending["pkg_id"], new_confidence=min(0.99, current_conf + 0.2))
    else:  # CORRECTED — genuinely retire it. "Retires unverified facts"
        # means removing a wrong fact, not leaving it sitting at a lower
        # number where it could still surface. retire_node() DETACH
        # DELETEs the Neo4j node and drops its pgvector shadow row
        # together (the existing P4 primitive for exactly this — a node
        # removed from only one store is the immortal-fact bug it
        # fixes). Not re-minting the corrected version David just gave
        # as a fresh fact — that's real, separate scope (item 3's
        # minter ruling governs what's allowed to mint, and re-minting
        # from a chat reply isn't dreaming), left for later.
        personal_kg.retire_node(pending["pkg_id"])

    logger.info(f"[verification_loop] {verdict} for pkg_id={pending['pkg_id']}")
    return {"pkg_id": pending["pkg_id"], "verdict": verdict}
