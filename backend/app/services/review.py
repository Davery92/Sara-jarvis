"""Review (SARA_MIND_V2_PLAN Phase 2/§3.7) — the editor pass on a composed
utterance, four checks: (1) worth his attention? (2) sounds like Sara?
(3) tense/temporal sanity — every referenced event's timing cross-checked
against the brief; (4) said before? (vs. 14-day utterance history).
Output: approve / edit / kill. "Expect and *want* a high kill rate early."

SHADOW MODE — see compose.py's module docstring. Review runs for real and
its verdict is persisted, but nothing downstream sends anything.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


async def gather_entity_history(db, user_id: str, dedupe_key: Optional[str],
                                days: int = 7) -> List[str]:
    """Everything already said about THIS entity, verbatim.

    The said-before check was comparing a draft against notification *titles*
    across all topics — a coarse-grained signal that missed the failure it exists
    to catch. On 2026-09-01 five paraphrases of one Laura Weippert concern went
    out in a morning: same entity, different titles, so nothing matched. The
    reviewer needs the actual text it already sent about this exact thing.
    """
    if not dedupe_key:
        return []
    from sqlalchemy import text as sa_text

    try:
        rows = (await db.execute(sa_text("""
            SELECT cu.final_text AS said, cu.delivered_at AS at
              FROM composed_utterance cu
              JOIN say_candidate sc ON sc.id = cu.candidate_id
             WHERE cu.user_id = :uid AND cu.delivered_at IS NOT NULL
               AND cu.final_text IS NOT NULL
               AND :key = ANY(sc.topic_entities)
               AND cu.delivered_at >= NOW() - (:days * INTERVAL '1 day')
            UNION ALL
            SELECT n.message AS said, n.sent_at AS at
              FROM notification_log n
             WHERE n.user_id = :uid AND n.sent = TRUE
               AND n.topic = :key
               AND n.sent_at >= NOW() - (:days * INTERVAL '1 day')
             ORDER BY at DESC LIMIT 10
        """), {"uid": user_id, "key": dedupe_key, "days": days})).fetchall()
        return [(r.said or "").strip() for r in rows if (r.said or "").strip()]
    except Exception as e:
        logger.warning(f"[review] entity history unavailable for {dedupe_key!r}: {e}")
        return []


def _build_prompt(composed_text: str, candidate: Dict[str, Any], brief_text: str,
                  utterance_history: List[Dict[str, Any]],
                  entity_history: Optional[List[str]] = None) -> Tuple[str, str]:
    hist_lines = [
        f"- \"{h['title']}\" ({h['category']}, {'engaged' if h['engaged'] else 'not engaged'})"
        for h in utterance_history[:20]
    ]
    hist_block = "\n".join(hist_lines) if hist_lines else "(no sends in the last 14 days)"

    entity_block = (
        "\n".join(f'- "{said[:300]}"' for said in (entity_history or [])[:10])
        or "(nothing said about this specific thing in the last 7 days)"
    )

    system_msg = (
        "You are Sara's editor: the last check before an unprompted message would go out. "
        "You are deliberately skeptical — a high kill rate is expected and correct, not a "
        "failure. Check the draft against four things:\n"
        "1. Worth his attention? Does it have a real payload (name/subject/event/number), "
        "or is it a disguised check-in?\n"
        "2. Does it sound like Sara — warm, sharp, specific — or generic/robotic/a service "
        "menu?\n"
        "3. Tense/temporal sanity: does every date/time reference in the draft match the "
        "World Brief below? A draft that says something is 'coming up' when the brief "
        "shows it already happened is a hard kill.\n"
        "4. Said before? First check ALREADY SAID ABOUT THIS EXACT THING below — if any "
        "line there makes the same point as this draft, however differently worded, that "
        "is a hard kill: he has already been told. Then check the wider utterance history "
        "for a substantially similar recent send.\n\n"
        "Respond with ONLY valid JSON:\n"
        '{"verdict": "approve|edit|kill", "reason": "one sentence, specific", '
        '"edited_text": "only present if verdict=edit — the corrected message"}'
    )

    user_msg = (
        f"## Draft message\n{composed_text}\n\n"
        f"## Original candidate\nkind: {candidate['kind']}\nsummary: {candidate['summary']}\n\n"
        f"## Current World Brief (for tense/temporal check)\n{brief_text}\n\n"
        f"## ALREADY SAID ABOUT THIS EXACT THING, last 7 days\n{entity_block}\n\n"
        f"## Utterance history, last 14 days (for said-before check)\n{hist_block}\n"
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
    raise json.JSONDecodeError("No valid JSON found in review response", text_, 0)


async def review_utterance(
    composed_text: str,
    candidate: Dict[str, Any],
    brief_text: str,
    utterance_history: List[Dict[str, Any]],
    entity_history: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Returns {"verdict": approve|edit|kill, "reason": str, "edited_text": Optional[str]}.
    Fails closed to kill on any error — an editor that can't render an opinion
    should not wave a message through."""
    system_msg, user_msg = _build_prompt(
        composed_text, candidate, brief_text, utterance_history, entity_history,
    )

    try:
        from app.core.llm import get_background_llm_client
        client = get_background_llm_client()
        response = await client.chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=400,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            caller="review",
        )
        raw = response["choices"][0]["message"].get("content", "") if isinstance(response, dict) else str(response)
        parsed = _parse_response(raw)
    except Exception as e:
        logger.warning(f"[review] LLM call/parse failed, failing closed to kill: {e}")
        return {"verdict": "kill", "reason": f"review_failed: {e}", "edited_text": None}

    verdict = parsed.get("verdict")
    if verdict not in ("approve", "edit", "kill"):
        return {"verdict": "kill", "reason": "review produced an invalid verdict", "edited_text": None}

    edited_text = parsed.get("edited_text") if verdict == "edit" else None
    if verdict == "edit" and not (edited_text or "").strip():
        # An "edit" verdict with no actual edited text is meaningless — treat as approve
        # of the original rather than silently losing the message to a malformed edit.
        verdict = "approve"

    return {
        "verdict": verdict,
        "reason": str(parsed.get("reason") or "")[:1000],
        "edited_text": (edited_text or "").strip()[:2000] if edited_text else None,
    }
