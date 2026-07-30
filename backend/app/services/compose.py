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

Per-candidate `send_now` composition (`compose_utterance`) plus batch-
digest composition (`compose_digest_utterance`, work-order item 12,
2026-07-30 — David's hybrid ruling): at a `mindv2-batch-flush` window,
3+ candidates compose into ONE coherent-paragraph utterance through this
same compose->review path; 1-2 still go through `compose_utterance`
individually (app/tasks/compose.py does the routing). This is NOT the
morning-brief/evening-close-out slot composition morning_brief_service.py
already owns separately — this is specifically for judge's own
`[slot=morning]`/`[slot=evening]` "worth mentioning, batched" candidates
once mindv2_batch_flush.py promotes them.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ComposeDeclined(Exception):
    """Raised when the compose model has nothing worth saying — distinct
    from a real failure (LLM error, bad JSON) so callers can log it as a
    quiet no-op instead of an error to investigate."""


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
    affect: Optional[Tuple[str, float, str]] = None,
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
        "already knows. If the candidate genuinely has no real payload once you try to "
        "write it, respond with \"text\": \"Silence.\" exactly — do NOT write a message "
        "ABOUT deciding not to send (no 'not sending this', no explaining why it's stale "
        "or a duplicate, no narrating the judge's reasoning back) — that text would still "
        "get treated as a real message.\n\n"
        "Respond with ONLY valid JSON:\n"
        '{"text": "the actual message", "refs": ["short evidence refs, e.g. entity or id strings"], '
        '"urgency": "normal|high|urgent|critical"}'
    )

    chat_lines = [
        f"- [{t['at'][:16] if t.get('at') else '?'}] {t['role']}: {t['content']}"
        for t in (recent_chat or [])
    ]
    chat_block = "\n".join(chat_lines) if chat_lines else "(no chat in the last 6 hours)"

    # Arc 4.4: "one affect, computed, consequential" — modulates tone, not
    # content. A real feeling with a real cause, phrased in like one sentence
    # of guidance, not a mood label slapped on top of the message.
    affect_block = ""
    if affect and affect[0] != "attentive":
        tone, intensity, about = affect
        strength = "a little" if intensity < 0.5 else "genuinely"
        affect_block = (
            f"\n## Your current mood (let this shape tone, not content)\n"
            f"You're {strength} feeling {tone} right now"
            + (f", about {about}" if about else "") + ". "
            "Let it color HOW you say this, not WHAT you say — don't mention "
            "the feeling explicitly, don't let it override the payload.\n"
        )

    user_msg = (
        f"## Current World Brief (for time-honesty — check any date/time claim against this)\n{brief_text}\n\n"
        f"## Recent conversation (last 6 hours)\n{chat_block}\n"
        f"{affect_block}\n"
        f"## Candidate\n"
        f"kind: {candidate['kind']}\n"
        f"summary: {candidate['summary']}\n"
        f"evidence: {json.dumps(candidate.get('evidence') or [])}\n"
        f"judge's reasoning: {candidate.get('judge_reason') or '(none)'}\n"
    )
    return system_msg, user_msg


def _build_digest_prompt(
    candidates: List[Dict[str, Any]], brief_text: str, voice_doc: str,
    recent_chat: List[Dict[str, Any]] = None,
    affect: Optional[Tuple[str, float, str]] = None,
) -> Tuple[str, str]:
    """Work-order item 12: N candidates -> ONE coherent-paragraph message,
    not a bulleted concatenation. Same voice/time-honesty/act-then-speak
    rules as single composition — the only real difference is the model
    is explicitly told to weave several things into one flowing update
    instead of writing about just one."""
    system_msg = (
        f"{voice_doc}\n\n"
        "---\n\n"
        "You are composing ONE unprompted message to David, in the voice above, that covers "
        "SEVERAL things at once — the judge batched these because none needed to interrupt him "
        "the moment they came up, but they're worth a single combined update now. This is NOT a "
        "reply — he didn't ask. Write it as ONE flowing, coherent paragraph in your own voice — "
        "genuinely weave the items together (by theme, by chronology, by what actually matters "
        "most first), NOT a bulleted list and NOT separate sentences that just happen to share a "
        "message. Never narrate the machinery (no 'my judge flagged these', no 'batch', no "
        "confidence numbers). Time-honest (check every date/time reference against the brief "
        "below). If a candidate genuinely has no real payload once you try to write it in, quietly "
        "drop that one item rather than padding the paragraph — but the message overall must still "
        "carry real content; if NONE of the candidates have real payload, respond with \"text\": "
        "\"Silence.\" exactly, same rule as single composition. Short overall — this is a digest, "
        "not a report; three or four sentences covering everything, not one per item.\n\n"
        "Respond with ONLY valid JSON:\n"
        '{"text": "the actual message", "refs": ["short evidence refs, e.g. entity or id strings"], '
        '"urgency": "normal|high|urgent|critical"}'
    )

    chat_lines = [
        f"- [{t['at'][:16] if t.get('at') else '?'}] {t['role']}: {t['content']}"
        for t in (recent_chat or [])
    ]
    chat_block = "\n".join(chat_lines) if chat_lines else "(no chat in the last 6 hours)"

    affect_block = ""
    if affect and affect[0] != "attentive":
        tone, intensity, about = affect
        strength = "a little" if intensity < 0.5 else "genuinely"
        affect_block = (
            f"\n## Your current mood (let this shape tone, not content)\n"
            f"You're {strength} feeling {tone} right now"
            + (f", about {about}" if about else "") + ". "
            "Let it color HOW you say this, not WHAT you say — don't mention "
            "the feeling explicitly, don't let it override the payload.\n"
        )

    candidates_block = "\n\n".join(
        f"### Item {i+1}\n"
        f"kind: {c['kind']}\n"
        f"summary: {c['summary']}\n"
        f"evidence: {json.dumps(c.get('evidence') or [])}\n"
        f"judge's reasoning: {c.get('judge_reason') or '(none)'}"
        for i, c in enumerate(candidates)
    )

    user_msg = (
        f"## Current World Brief (for time-honesty — check any date/time claim against this)\n{brief_text}\n\n"
        f"## Recent conversation (last 6 hours)\n{chat_block}\n"
        f"{affect_block}\n"
        f"## Batched items ({len(candidates)}) — weave into one message\n{candidates_block}\n"
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


async def _read_affect(user_id: Optional[str]) -> Optional[Tuple[str, float, str]]:
    """Arc 4.4: current affect modulates tone. Best-effort — a broken read
    must never block composition, same as every other context fetch."""
    try:
        from app.services.working_memory import read_memory
        from app.services.emotional_state import DEFAULT_USER_ID
        snap = await read_memory(user_id or DEFAULT_USER_ID)
        if snap.sara_emotional_tone:
            return (snap.sara_emotional_tone, snap.sara_emotional_intensity or 0.3, snap.sara_emotional_about or "")
    except Exception as e:
        logger.debug(f"[compose] affect read skipped: {e}")
    return None


def _is_decline(text: str) -> bool:
    """The prompt explicitly asks for a literal "Silence." on a too-thin
    candidate (Arc 5, work-order item 5 — a real kill-rate audit found
    ~18% of kills were the model narrating its own decision not to send
    instead: "Not sending this...", "The rain candidate was stale, so I'm
    sending silence.", "Nothing to report — the pipeline is clear." —
    meta-commentary that review correctly killed, but composed a real LLM
    call and a fake-looking utterance row to do it). Defensive backstop in
    case the model still doesn't comply with the explicit instruction:
    catch the same self-narrating-about-not-sending shape by pattern, not
    just the canonical "Silence." string."""
    _decline_narration = re.match(
        r"^(not sending|nothing to (report|send)|i'?m (not sending|keeping (it |this )?quiet|"
        r"sending silence)|the [\w\s]{0,30} candidate (is|was) stale)\b",
        text.lower(),
    )
    return not text or text.lower().rstrip(".") == "silence" or bool(_decline_narration)


async def _call_compose_llm(system_msg: str, user_msg: str) -> Dict[str, Any]:
    """Shared LLM call + response validation for both single and digest
    composition — same model, same decline detection, same output shape."""
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
    if _is_decline(text):
        raise ComposeDeclined("model declined to compose — no real payload")

    return {
        "text": text[:2000],
        "refs": [str(r)[:200] for r in (parsed.get("refs") or [])][:10],
        "urgency": parsed.get("urgency") if parsed.get("urgency") in
                   ("normal", "high", "urgent", "critical") else "normal",
    }


async def compose_utterance(
    candidate: Dict[str, Any], brief_text: str, recent_chat: List[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns {"text", "refs", "urgency"} — the ComposedUtterance shape
    (minus `slot`, which per-candidate immediate composition doesn't use)."""
    voice_doc = _load_voice_doc()
    affect = await _read_affect(user_id)
    system_msg, user_msg = _build_prompt(candidate, brief_text, voice_doc, recent_chat, affect=affect)
    return await _call_compose_llm(system_msg, user_msg)


async def compose_digest_utterance(
    candidates: List[Dict[str, Any]], brief_text: str, recent_chat: List[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Work-order item 12: N (3+) batched candidates -> ONE coherent-
    paragraph ComposedUtterance, same shape as compose_utterance. Caller
    (app/tasks/compose.py) is responsible for the 3+ threshold and for
    marking every contributing candidate's status individually — this
    function only composes the text."""
    if len(candidates) < 2:
        raise ValueError("compose_digest_utterance needs at least 2 candidates — use compose_utterance for one")
    voice_doc = _load_voice_doc()
    affect = await _read_affect(user_id)
    system_msg, user_msg = _build_digest_prompt(candidates, brief_text, voice_doc, recent_chat, affect=affect)
    return await _call_compose_llm(system_msg, user_msg)
