"""Skill minting — the dreaming-state trigger (SARA_ALIVE §4/Arc 6.5, 2026-07-31).

Design published 2026-07-31 (https://claude.ai/code/artifact/aa35b186-8023-
4991-9a37-dc0b5867c921): fumble detection (evidence-only) -> draft authoring
-> static validation -> sandbox dry-run against the draft's own self-
generated test cases -> propose (sara_tool row, enabled=FALSE) -> queue for
David's review. The enable click stays David's — that boundary is the
feature, not a stop condition this pass declines to cross.

Kill-switched by Flag.SKILL_MINTING (default off) — gates only this
function's write path, never /invoke, so disabling new proposals never
revokes a tool David has already enabled.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

_AUTHOR_PROMPT = """Sara noticed a real, repeated fumble and may be able to fix it by minting herself a
new tool. Evidence (not a hypothesis — this actually happened):

{evidence}

Decide first: is this genuinely fixable by a NEW tool (a capability that doesn't exist yet), or is
it actually a bug in an EXISTING tool / process (which minting a new tool can't fix and would be
the wrong response to)? If it's the latter, or you're not confident a clean tool addresses it,
return {{"skip": true, "reason": "..."}}.

If a new tool genuinely helps, author one. Requirements for the code:
- A single top-level `def run(args: dict) -> dict`.
- Only these imports are available: httpx, json, re, datetime, math, collections, itertools,
  functools, typing, statistics, urllib.parse, hashlib, base64, string, decimal, fractions, random, html.
- No filesystem, no subprocess, no eval/exec, no dunder tricks — the sandbox has no network
  isolation but does statically reject those.
- Keep it small and focused on the one fumble.

You must also supply 2-3 test cases the tool should pass — at minimum one covering the exact
fumble evidence above, plus one edge case. Each test case is {{"args": {{...}}, "expect_ok": true|false}}
(expect_ok=false means you expect run() to raise or return an error-shaped result for that input —
useful for confirming the tool fails gracefully on bad input, not just that it succeeds on good input).

Return ONLY valid JSON:
{{"skip": false, "name": "snake_case_name", "description": "one sentence", "args_schema": {{JSON Schema, type object}}, "code": "...", "test_cases": [{{"args": {{...}}, "expect_ok": true}}, ...], "notes": "why this addresses the fumble"}}
or
{{"skip": true, "reason": "..."}}"""


def _evidence_text(error_fumbles: List[Dict[str, Any]], sequence_fumbles: List[Dict[str, Any]]) -> str:
    parts = []
    for f in error_fumbles[:3]:
        parts.append(
            f"- Tool '{f['tool']}' has failed with {f['error_class']} {f['n']} times in the last "
            f"7 days. Sample error: {f.get('sample_error', '')[:300]}"
        )
    for f in sequence_fumbles[:3]:
        parts.append(
            f"- David has manually chained this exact tool sequence {f['count']} separate times "
            f"in the last 14 days: {' -> '.join(f['sequence'])}"
        )
    return "\n".join(parts)


async def _author_draft(evidence_text: str) -> Optional[Dict[str, Any]]:
    try:
        import httpx
        from app.services.llm_broker import resolve as resolve_capability

        cap = resolve_capability("utility")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{cap['base_url']}/chat/completions",
                json={
                    "model": cap["model"],
                    "messages": [{"role": "user", "content": _AUTHOR_PROMPT.format(evidence=evidence_text)}],
                    "temperature": 0.3,
                    "max_tokens": 1800,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content.strip())
    except Exception as e:
        logger.warning(f"[skill_minting] draft authoring failed: {e}")
        return None


async def _dry_run(code: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Executes the draft against one test case via the same acs-tool-runner
    sandbox real invocations use, but bypasses sara_tool_invocation entirely
    — a dry-run isn't a real invocation and the tool doesn't exist in the DB
    yet at this point in the pipeline."""
    import httpx
    import uuid
    from app.core.config import settings

    runner_url = (getattr(settings, "acs_tool_runner_url", "") or "").rstrip("/")
    if not runner_url:
        return {"error": "tool runner not configured"}
    async with httpx.AsyncClient(timeout=35.0) as client:
        resp = await client.post(
            f"{runner_url}/run",
            json={"invocation_id": f"dryrun-{uuid.uuid4().hex[:12]}", "code": code, "args": args},
            headers={"X-Daemon-Token": getattr(settings, "acs_daemon_token", "") or ""},
        )
        resp.raise_for_status()
        return resp.json()


async def _run_test_cases(code: str, test_cases: List[Dict[str, Any]]) -> Optional[str]:
    """Returns None if all test cases pass their expectation, else a string
    describing which one failed and how."""
    for i, case in enumerate(test_cases):
        result = await _dry_run(code, case.get("args") or {})
        got_error = bool(result.get("error"))
        expect_ok = case.get("expect_ok", True)
        if expect_ok and got_error:
            return f"test case {i} expected success but got error: {result.get('error')}"
        if not expect_ok and not got_error:
            return f"test case {i} expected a failure but the tool returned a result: {result.get('result')}"
    return None


async def maybe_propose_skill(db: Session, user_id: str = _DAVID_USER_ID) -> Optional[Dict[str, Any]]:
    """The full pipeline, one attempt per call. Returns the proposed tool's
    name if a draft was successfully queued for David's review, else None
    (flag off, no fumble evidence, the model declined, validation/dry-run
    failed, or a proposal is already pending review)."""
    from app.core.feature_flags import Flag, is_enabled
    if not is_enabled(Flag.SKILL_MINTING):
        return None

    from sqlalchemy import text as sql_text
    pending = db.execute(sql_text(
        "SELECT name FROM sara_tool WHERE enabled = FALSE LIMIT 1"
    )).fetchone()
    if pending:
        logger.debug(f"[skill_minting] a draft is already pending review ({pending.name}); skipping")
        return None

    from app.services.fumble_detector_service import detect_error_fumbles, detect_sequence_fumbles
    error_fumbles = detect_error_fumbles(db)
    sequence_fumbles = detect_sequence_fumbles(db)
    if not error_fumbles and not sequence_fumbles:
        return None

    evidence_text = _evidence_text(error_fumbles, sequence_fumbles)
    draft = await _author_draft(evidence_text)
    if not draft or draft.get("skip"):
        if draft:
            logger.info(f"[skill_minting] model declined to mint: {draft.get('reason')}")
        return None

    from app.services.acs_tool_validator import ToolValidationError, validate_args_schema, validate_tool_code
    try:
        validate_args_schema(draft["args_schema"])
        validate_tool_code(draft["code"])
    except (ToolValidationError, KeyError) as e:
        logger.warning(f"[skill_minting] draft failed static validation, discarding: {e}")
        return None

    test_cases = draft.get("test_cases") or []
    if not test_cases:
        logger.warning("[skill_minting] draft shipped no test cases, discarding")
        return None
    failure = await _run_test_cases(draft["code"], test_cases)
    if failure:
        logger.warning(f"[skill_minting] draft failed its own test cases, discarding: {failure}")
        return None

    existing = db.execute(sql_text(
        "SELECT id FROM sara_tool WHERE name = :name"
    ), {"name": draft["name"]}).fetchone()
    if existing:
        logger.info(f"[skill_minting] tool name '{draft['name']}' already exists, discarding duplicate draft")
        return None

    tool_row = db.execute(sql_text("""
        INSERT INTO sara_tool (name, description, args_schema)
        VALUES (:name, :description, CAST(:schema AS jsonb))
        RETURNING id
    """), {
        "name": draft["name"], "description": draft["description"],
        "schema": json.dumps(draft["args_schema"]),
    }).fetchone()
    tool_id = tool_row.id

    version_row = db.execute(sql_text("""
        INSERT INTO sara_tool_version (tool_id, version, code, notes)
        VALUES (:tool_id, 1, :code, :notes)
        RETURNING id
    """), {"tool_id": tool_id, "code": draft["code"], "notes": draft.get("notes", "")}).fetchone()

    db.execute(sql_text(
        "UPDATE sara_tool SET active_version_id = :vid WHERE id = :tid"
    ), {"vid": version_row.id, "tid": tool_id})
    db.commit()

    logger.info(f"[skill_minting] proposed new tool '{draft['name']}', queued for David's review")

    try:
        from app.services.unified_notification import send_notification
        await send_notification(
            user_id=user_id,
            title="I drafted a new tool",
            message=f"\"{draft['name']}\": {draft['description']} — it passed its own tests. Review it in ACS when you get a chance.",
            priority="low",
            topic=f"skill_minting_proposal:{draft['name']}",
            category="general",
            source="skill_minting_service",
        )
    except Exception as e:
        logger.debug(f"[skill_minting] proposal notice skipped: {e}")

    return draft["name"]
