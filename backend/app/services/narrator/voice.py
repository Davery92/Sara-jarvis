"""Narrator voice — call the fast-tier Qwen and shape it into a SystemEvent.

Single entry point: `generate(trigger_context, recent_events)`. Returns a
dict ready to be merged into a SystemEventPayload, or None if the model
refuses to produce something in-voice after one retry.

Why fast tier (Qwen3.5-35B-A3B):
- Short outputs (1-3 sentences), high frequency. Doesn't fight ACS for the
  big primary model.
- Latency matters because the desktop popup wants to feel reactive.

What this file guards against:
- Forbidden vocabulary that breaks persona (`great job`, `amazing`, `lol`).
- Length blowups (model drifts into paragraphs).
- Missing the JSON contract (markdown fences, preamble).
- Drift away from the trigger_context facts (model invents details).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.core.llm_config import llm_config
from app.services.narrator.triggers.base import TriggerContext

logger = logging.getLogger(__name__)


# Prompt templates. Patch notes + sponsored interjections use different
# personas/structures than ad-hoc trigger output, so the voice picks the
# right template based on a name passed in by the caller.
_PROMPTS_DIR = Path(__file__).parent / "prompts"
_PROMPT_PATH = _PROMPTS_DIR / "narrator_v1.txt"  # legacy alias

PROMPT_TEMPLATES = {
    "narrator_v1": "narrator_v1.txt",
    "patch_note_v1": "patch_note_v1.txt",
    "sponsored_v1": "sponsored_v1.txt",
}

# Per-template max-body cap. Patch notes are intentionally longer (4-8 bullets).
TEMPLATE_BODY_CAP = {
    "narrator_v1": 480,
    "patch_note_v1": 1400,
    "sponsored_v1": 320,
}

# Per-template max output tokens.
TEMPLATE_MAX_TOKENS = {
    "narrator_v1": 240,
    "patch_note_v1": 700,
    "sponsored_v1": 200,
}

# Drift guards. These are case-insensitive substring checks against the
# generated body. Hits trigger a corrective retry; second-pass hits fall
# back to a deterministic template.
FORBIDDEN_SUBSTRINGS = (
    "great job",
    "well done",
    "keep it up",
    "you got this",
    "proud of you",
    "i notice",
    "i'm noticing",
    "amazing",
    "awesome",
    "incredible",
    "lol",
    "lmao",
)

# Hard length cap. Voice rules say 1-3 sentences; this is the safety net.
MAX_BODY_CHARS = 480
MAX_TITLE_CHARS = 80


@dataclass
class GeneratedUtterance:
    title: str
    body: str
    subtitle: Optional[str]
    raw_model_output: str
    retried: bool
    fell_back: bool


def _load_prompt(template: str = "narrator_v1") -> str:
    filename = PROMPT_TEMPLATES.get(template)
    if not filename:
        raise ValueError(f"unknown narrator prompt template: {template!r}")
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _build_user_message(
    ctx: TriggerContext,
    recent_events: List[Dict[str, Any]],
) -> str:
    """Build the user-side input. Recent events go at the *tail* so the
    stable persona prompt + trigger payload are at the head (where prompt
    caching, if the server honors it, would help)."""
    lines = [
        "TriggerContext:",
        json.dumps(
            {
                "trigger_name": ctx.trigger_name,
                "severity": ctx.severity,
                "facts": ctx.facts,
                "summary": ctx.summary,
            },
            indent=2,
        ),
    ]
    if recent_events:
        lines.append("")
        lines.append(
            "Recent narrator output (avoid repeating these titles or "
            "phrasings — the System is bored, not repetitive):"
        )
        for ev in recent_events[-5:]:
            title = ev.get("title", "")
            body = (ev.get("body") or "")[:120]
            sev = ev.get("severity", "")
            lines.append(f"  [{sev}] {title} — {body}")
    return "\n".join(lines)


async def _call_model(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = 0.9,
    max_tokens: int = 240,
    extra_system: Optional[str] = None,
) -> str:
    """One LLM round-trip. Returns raw assistant content (string)."""
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if extra_system:
        messages.append({"role": "system", "content": extra_system})
    messages.append({"role": "user", "content": user_message})

    timeout = float(os.environ.get("NARRATOR_LLM_TIMEOUT", "30"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{llm_config.fast_model_url}/chat/completions",
            json={
                "model": llm_config.fast_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                # Qwen3 is a reasoning model — without this, its chain of
                # thought eats the token budget and `content` comes back empty.
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        resp.raise_for_status()
        data = resp.json()
    msg = data["choices"][0]["message"]
    # Defensive: some servers still emit into reasoning_content even with
    # thinking disabled.
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Be liberal in what we accept — Qwen sometimes wraps JSON in fences
    or adds a stray preamble line. We just want the first JSON object."""
    text = text.strip()
    if not text:
        return None

    # Try direct parse first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try a fenced block.
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try the first {...} balanced span by character scan.
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _validate(parsed: Dict[str, Any], body_cap: int = MAX_BODY_CHARS) -> Optional[str]:
    """Return None if the parsed output is acceptable, else a short reason
    string used for the corrective retry's extra_system message."""
    title = (parsed.get("title") or "").strip()
    body = (parsed.get("body") or "").strip()

    if not title or not body:
        return "Output must include non-empty 'title' and 'body' fields."

    if len(title) > MAX_TITLE_CHARS:
        return f"Title is too long ({len(title)} chars); cap at {MAX_TITLE_CHARS}."
    if len(body) > body_cap:
        return f"Body is too long ({len(body)} chars); cap at {body_cap}."

    lower = body.lower()
    for bad in FORBIDDEN_SUBSTRINGS:
        if bad in lower:
            return (
                f"Body contains forbidden phrase {bad!r}. The System AI is "
                "weary and contemptuous, not encouraging. Rewrite without that."
            )

    # No questions to the user.
    if "?" in body:
        return (
            "Body contains a question mark. The System narrates; it does "
            "not ask the user questions. Rewrite as a statement."
        )

    return None


def _fallback_template(ctx: TriggerContext) -> Dict[str, str]:
    """Deterministic last resort if the model can't stay in voice after a
    retry. Uses the facts directly. Not poetic, but never breaks persona."""
    facts = ctx.facts
    if ctx.trigger_name == "stale_pr":
        n = facts.get("pr_count", "?")
        branch = facts.get("oldest_branch", "unknown")
        age = facts.get("oldest_age_days", "?")
        return {
            "title": "PENDING",
            "body": (
                f"{n} open pull request"
                f"{'s' if n != 1 else ''}. The oldest, {branch}, "
                f"has been open for {age} day{'s' if age != 1 else ''}."
            ),
            "subtitle": None,
        }
    # Generic fallback.
    return {
        "title": "NOTED",
        "body": ctx.summary,
        "subtitle": None,
    }


async def generate(
    ctx: TriggerContext,
    recent_events: Optional[List[Dict[str, Any]]] = None,
    *,
    prompt_template: str = "narrator_v1",
) -> GeneratedUtterance:
    """Generate an in-voice utterance for a TriggerContext.

    `prompt_template` selects between voice modes:
    - "narrator_v1" (default) — tight, 1-3 sentences, ad-hoc trigger output
    - "patch_note_v1" — fake release notes, 4-8 bullets, corporate cadence
    - "sponsored_v1" — absurdist commercial non-sequitur

    Tries once at normal temperature. If validation fails, retries once with
    an explicit corrective system message. If that still fails, returns the
    deterministic template.
    """
    system_prompt = _load_prompt(prompt_template)
    user_msg = _build_user_message(ctx, recent_events or [])
    body_cap = TEMPLATE_BODY_CAP.get(prompt_template, MAX_BODY_CHARS)
    max_tokens = TEMPLATE_MAX_TOKENS.get(prompt_template, 240)

    raw1 = ""
    try:
        raw1 = await _call_model(system_prompt, user_msg, max_tokens=max_tokens)
    except Exception as exc:
        logger.warning("narrator: first LLM call failed: %s", exc)

    parsed1 = _extract_json(raw1) if raw1 else None
    if parsed1:
        reason = _validate(parsed1, body_cap=body_cap)
        if reason is None:
            return GeneratedUtterance(
                title=parsed1["title"].strip(),
                body=parsed1["body"].strip(),
                subtitle=(parsed1.get("subtitle") or None),
                raw_model_output=raw1,
                retried=False,
                fell_back=False,
            )
        logger.info("narrator: first pass rejected (%s) — retrying", reason)
    else:
        reason = "Previous output was not valid JSON; return ONLY a JSON object."
        logger.info("narrator: first pass produced no JSON — retrying")

    raw2 = ""
    try:
        raw2 = await _call_model(
            system_prompt,
            user_msg,
            temperature=0.7,
            max_tokens=max_tokens,
            extra_system=(
                f"Your previous attempt was rejected. Reason: {reason} "
                "Return ONLY a single JSON object with title, body, and "
                "optional subtitle. No preamble, no markdown."
            ),
        )
    except Exception as exc:
        logger.warning("narrator: retry LLM call failed: %s", exc)

    parsed2 = _extract_json(raw2) if raw2 else None
    if parsed2 and _validate(parsed2, body_cap=body_cap) is None:
        return GeneratedUtterance(
            title=parsed2["title"].strip(),
            body=parsed2["body"].strip(),
            subtitle=(parsed2.get("subtitle") or None),
            raw_model_output=raw2,
            retried=True,
            fell_back=False,
        )

    logger.warning(
        "narrator: both passes rejected for %s; using template fallback",
        ctx.trigger_name,
    )
    fb = _fallback_template(ctx)
    return GeneratedUtterance(
        title=fb["title"],
        body=fb["body"],
        subtitle=fb.get("subtitle"),
        raw_model_output=raw2 or raw1,
        retried=True,
        fell_back=True,
    )
