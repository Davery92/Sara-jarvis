"""Compose (SARA_MIND_V2_PLAN Phase 2/§3.7) — writes the actual outbound
message for a judge-approved (`judged_send`) candidate: voice doc +
exemplars + brief + candidate evidence (including any completed prep) ->
a ComposedUtterance.

SHADOW MODE — this session's explicit scope decision, consistent with
appraisal.py and judge.py: composed utterances are persisted to
`composed_utterance` for inspection (so quality can actually be judged
over the coming days), but nothing reads this table for delivery. This is
the schema/pipeline Phase 2's real cutover will eventually point delivery
at — building it now, dark, is what lets a shadow week start accumulating
real examples instead of beginning the moment someone finally sits down
to write Compose from scratch.

Only per-candidate `send_now` composition is built here. Slot composition
(the morning brief / evening close-out becoming a single coherent message
from a batch) is NOT — that would mean touching morning_brief_service.py's
existing, separately-owned generation path, which is out of scope for a
shadow-mode addition.
"""
import json
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def _load_voice_doc() -> str:
    try:
        from pathlib import Path
        doc_path = Path(__file__).resolve().parent.parent / "prompts" / "sara_voice.md"
        return doc_path.read_text()
    except Exception as e:
        logger.warning(f"[compose] voice doc load failed: {e}")
        return (
            "You are Sara, David's personal AI assistant — Syl's bubbly, curious energy "
            "with Cortana's competence. Warm, sharp, genuinely invested."
        )


def _build_prompt(
    candidate: Dict[str, Any], brief_text: str, voice_doc: str,
    recent_chat: List[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    system_msg = (
        f"{voice_doc}\n\n"
        "---\n\n"
        "You are composing ONE unprompted message to David, in the voice above. This is "
        "not a reply — he didn't ask. The candidate below is a raw fact plus a judge's "
        "reasoning for why it's worth telling him; your job is to turn it into the actual "
        "message, in your own voice, following the 'How Sara Speaks (unprompted)' rules "
        "above — payload, not a check-in; act-then-speak phrasing if prep already "
        "happened; never narrate the machinery (no 'my judge flagged this', no confidence "
        "numbers); time-honest (check every date/time reference against the brief below); "
        "short — one to three sentences. If the recent conversation already covers this "
        "ground, phrase around what was said — add the new part, don't repeat what David "
        "already knows.\n\n"
        "Respond with ONLY valid JSON:\n"
        '{"text": "the actual message", "refs": ["short evidence refs, e.g. entity or id strings"], '
        '"urgency": "normal|high|urgent|critical"}'
    )

    chat_lines = [
        f"- [{t['at'][:16] if t.get('at') else '?'}] {t['role']}: {t['content']}"
        for t in (recent_chat or [])
    ]
    chat_block = "\n".join(chat_lines) if chat_lines else "(no chat in the last 6 hours)"

    user_msg = (
        f"## Current World Brief (for time-honesty — check any date/time claim against this)\n{brief_text}\n\n"
        f"## Recent conversation (last 6 hours)\n{chat_block}\n\n"
        f"## Candidate\n"
        f"kind: {candidate['kind']}\n"
        f"summary: {candidate['summary']}\n"
        f"evidence: {json.dumps(candidate.get('evidence') or [])}\n"
        f"judge's reasoning: {candidate.get('judge_reason') or '(none)'}\n"
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
    raise json.JSONDecodeError("No valid JSON found in compose response", text_, 0)


async def compose_utterance(
    candidate: Dict[str, Any], brief_text: str, recent_chat: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Returns {"text", "refs", "urgency"} — the ComposedUtterance shape
    (minus `slot`, which per-candidate immediate composition doesn't use)."""
    voice_doc = _load_voice_doc()
    system_msg, user_msg = _build_prompt(candidate, brief_text, voice_doc, recent_chat)

    from app.core.llm import get_background_llm_client
    client = get_background_llm_client()
    response = await client.chat_completion(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.5,
        max_tokens=400,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    raw = response["choices"][0]["message"].get("content", "") if isinstance(response, dict) else str(response)
    parsed = _parse_response(raw)

    text = str(parsed.get("text") or "").strip()
    if not text:
        raise ValueError("compose produced empty text")

    return {
        "text": text[:2000],
        "refs": [str(r)[:200] for r in (parsed.get("refs") or [])][:10],
        "urgency": parsed.get("urgency") if parsed.get("urgency") in
                   ("normal", "high", "urgent", "critical") else "normal",
    }
