"""Appraisal loop (SARA_MIND_V2_PLAN Phase 3, §3.4) — the always-on process
that decides what's worth remembering (World Brief patches) and what might
be worth saying (say_candidates), from a batch of raw signals.

Reads the SAME event-bus-derived queue deliberation.py already reads
(`observation_log.get_pending_observations`) rather than re-subscribing to
the raw event bus directly — the observation log already is that batched,
salience-scored queue, and building a second consumer of the same bus would
just be two systems racing to drain it. One small-model call per batch,
producing structured JSON: `brief_patches[]`, `candidates[]`, `nothing`.

Status: ADDITIVE / dark, per this session's explicit scope decision. This
does NOT retire `salience.py`, `observation_log`, `should_deliberate`, or
`deliberation.py` — those keep running unchanged, and `kernel.ambient_turn`
is NOT yet cut over to appraisal->judge. The plan's Phase 3 "retire" list is
a deliberate, separate cutover decision — building the new path and turning
off the old one are different amounts of risk and shouldn't be bundled.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

from app.core.timezone import now as local_now
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()

# Cheap pre-check (§6 Phase 3 accept: "empty-LLM-run ratio < 20%", was 94%
# for deliberation). A batch that's 100% ambient (ambient category AND below
# the salience floor) skips the LLM entirely — no observation worth an
# appraisal call, so there's nothing an LLM would add over just... nothing.
_AMBIENT_CATEGORIES = {"system", "rhythm", "activity"}
_AMBIENT_SALIENCE_FLOOR = 0.6

_OBSERVATION_BATCH_LIMIT = 30


def _all_ambient(observations: List[Any]) -> bool:
    if not observations:
        return True
    return all(
        (obs.category in _AMBIENT_CATEGORIES and obs.salience < _AMBIENT_SALIENCE_FLOOR)
        for obs in observations
    )


def _build_prompt(observations: List[Any], brief_text: str, interest_text: str) -> Tuple[str, str]:
    now_str = local_now().strftime("%A, %B %-d, %Y, %-I:%M %p ET")

    obs_lines = [
        f"- [{o.category}] {o.description} (salience {o.salience:.2f}, source={o.source})"
        for o in observations[:_OBSERVATION_BATCH_LIMIT]
    ]
    obs_block = "\n".join(obs_lines) if obs_lines else "(none)"

    system_msg = (
        "You are Sara's appraisal loop: the always-on process that turns raw signals into "
        "two things, and two things only. You do NOT write outbound messages — a separate "
        "judge/compose step owns that.\n\n"
        "1. brief_patches[] — updates to Sara's World Brief, the one continuously-maintained "
        "record of what happened / is happening / is ahead / is open / needs a reply. Only "
        "patch a section when a signal genuinely changes it. Most batches patch nothing at "
        "all — activity without new information is not a patch.\n"
        "2. candidates[] — things that MIGHT be worth telling David later. Each candidate is "
        "a raw fact plus a value guess, not a phrased message, and carries a mandatory expiry "
        "(valid_until) so a stale candidate can never surface after its moment has passed. "
        "Most batches produce zero candidates: a candidate needs concrete, David-relevant new "
        "information (a name, an event, a number, a reply), not just ambient activity.\n\n"
        "Respond with ONLY valid JSON in this exact shape:\n"
        "{\n"
        '  "brief_patches": [\n'
        '    {"op": "add|update|close|move",\n'
        '     "section": "happened|ahead|open_loops|comms_needing_action|health_deltas",\n'
        '     "item_key": "short-stable-slug-for-this-item",\n'
        '     "content": {"text": "...", "at": "ISO-8601 timestamp or null"},\n'
        '     "target_section": "only present for op=move"}\n'
        "  ],\n"
        '  "candidates": [\n'
        '    {"kind": "inform|followup|prep|alert|retrospective",\n'
        '     "summary": "what could be said - the substance, NOT final phrasing",\n'
        '     "topic_entities": ["lowercase", "topic", "words", "or", "names"],\n'
        '     "value_guess": 0.0,\n'
        '     "valid_until": "ISO-8601 timestamp - REQUIRED for kind=prep or kind=followup "'
        '"(the event start / thread window); optional for inform/alert/retrospective "'
        '"(sane defaults apply if omitted)",\n'
        '     "evidence": [{"...": "any small evidence ref, e.g. an id or a quoted line"}]}\n'
        "  ],\n"
        '  "nothing": true only if this batch produced zero patches and zero candidates\n'
        "}\n\n"
        "Never invent a recurring routine or relationship you don't see evidence for above. "
        "Never restate something the brief already says unchanged — that isn't a patch. This "
        "applies especially to health_deltas: only patch it when a health reading has actually "
        "changed from what the brief already states, and set \"at\" to when the measurement "
        "itself was taken (never the current time / when you're writing this patch — if the "
        "exact measurement time isn't in the signal, use null rather than guessing now)."
    )

    user_msg = (
        f"AS OF: {now_str}\n\n"
        f"## Current World Brief\n{brief_text}\n\n"
        f"## Interest Model (what David cares about)\n{interest_text}\n\n"
        f"## New signals since last appraisal ({len(observations)} pending)\n{obs_block}\n"
    )
    return system_msg, user_msg


def _parse_response(raw: str) -> dict:
    """Parse LLM response as JSON, handling markdown fences and leading
    prose — same salvage shape as deliberation.py's _parse_response."""
    text = (raw or "").strip()

    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            inner = parts[1]
            if inner.startswith("json"):
                inner = inner[4:]
            text = inner.strip()
        else:
            lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    brace_idx = text.find("{")
    if brace_idx > 0:
        try:
            return json.loads(text[brace_idx:])
        except json.JSONDecodeError:
            pass

    if brace_idx >= 0:
        last_brace = text.rfind("}")
        if last_brace > brace_idx:
            try:
                return json.loads(text[brace_idx:last_brace + 1])
            except json.JSONDecodeError:
                pass

    raise json.JSONDecodeError("No valid JSON found in appraisal response", text, 0)


async def _apply_brief_patch(db, user_id: str, patch: Dict[str, Any]) -> None:
    from app.services.world_brief import brief_patch, SECTIONS, get_brief_row

    op = patch.get("op")
    section = patch.get("section")
    item_key = patch.get("item_key") or patch.get("key")
    if op not in ("add", "update", "close", "move") or section not in SECTIONS or not item_key:
        raise ValueError(f"invalid brief patch shape: {patch}")

    content = patch.get("content") if isinstance(patch.get("content"), dict) else {}

    if section == "health_deltas" and op in ("add", "update"):
        # health_deltas patches come from a small model reading a bare
        # "Weight 240.00 lbs" observation with no date attached — left to
        # its own devices it fills `at` with a guess of "now" every cycle,
        # which differs run to run even when the reading hasn't moved,
        # defeating brief_patch's item-equality no-op guard (same class of
        # bug as the sara_state clock leak fixed in b52b188c). Compare the
        # VALUE (text) against the brief's current item and drop the patch
        # outright when unchanged — an unchanged reading isn't a delta, so
        # there's nothing to record regardless of what `at` says.
        state = await get_brief_row(db, user_id)
        existing = next(
            (i for i in state["sections"].get("health_deltas", []) if i.get("key") == item_key),
            None,
        )
        if existing is not None and existing.get("text") == content.get("text"):
            return

    await brief_patch(
        db, user_id, op=op, section=section, item_key=str(item_key)[:200],
        content=content, source="appraisal", evidence=patch.get("evidence") or [],
        target_section=patch.get("target_section"),
    )


async def _create_candidate_from_appraisal(db, user_id: str, cand: Dict[str, Any]) -> None:
    from app.services.say_candidate import create_candidate

    kind = cand.get("kind")
    summary = cand.get("summary")
    if not kind or not summary:
        raise ValueError(f"invalid candidate shape: {cand}")

    valid_until = None
    vu_raw = cand.get("valid_until")
    if vu_raw:
        try:
            valid_until = datetime.fromisoformat(vu_raw)
        except (ValueError, TypeError):
            valid_until = None

    value_guess = cand.get("value_guess")
    try:
        value_guess = float(value_guess) if value_guess is not None else None
    except (TypeError, ValueError):
        value_guess = None

    await create_candidate(
        db, user_id, source="appraisal", kind=kind, summary=str(summary)[:2000],
        evidence=cand.get("evidence") or [],
        topic_entities=[str(t)[:60] for t in (cand.get("topic_entities") or [])][:10],
        value_guess=value_guess,
        valid_until=valid_until,
    )


async def run_appraisal(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """One appraisal cycle. Returns a summary dict (also written to
    agent_run_log by the caller) for observability."""
    from app.services.observation_log import get_pending_observations, consume_observations

    observations = await get_pending_observations(user_id, min_salience=0.0, limit=_OBSERVATION_BATCH_LIMIT)

    if _all_ambient(observations):
        return {"skipped": "all_ambient", "observations": len(observations)}

    from app.services.world_brief import get_rendered_brief
    from app.services.interest_model import get_rendered_interest_model
    from app.db.session import get_async_session_factory

    factory = get_async_session_factory()
    async with factory() as db:
        brief_text = await get_rendered_brief(db, user_id)
        interest_text = await get_rendered_interest_model(db, user_id)

    system_msg, user_msg = _build_prompt(observations, brief_text, interest_text)

    try:
        from app.core.llm import get_background_llm_client
        client = get_background_llm_client()
        response = await client.chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=1200,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = response["choices"][0]["message"].get("content", "") if isinstance(response, dict) else str(response)
    except Exception as e:
        logger.error(f"[appraisal] LLM call failed: {e}")
        # Fail-open on consumption: an LLM outage shouldn't let the same
        # batch re-trigger forever, but it also shouldn't silently drop
        # observations without a trace — log and leave them pending so the
        # next cycle retries (bounded by the 24h observation TTL).
        return {"error": str(e)}

    try:
        parsed = _parse_response(raw)
    except Exception as e:
        logger.warning(f"[appraisal] parse failed: {e}. Raw: {raw[:200]}")
        await consume_observations(user_id, [o.id for o in observations])
        return {"error": f"parse_failed: {e}"}

    stats = {"brief_patches": 0, "candidates": 0, "nothing": bool(parsed.get("nothing"))}
    async with factory() as db:
        for patch in parsed.get("brief_patches", []) or []:
            try:
                await _apply_brief_patch(db, user_id, patch)
                stats["brief_patches"] += 1
            except Exception as e:
                logger.warning(f"[appraisal] brief patch skipped ({e}): {patch}")

        for cand in parsed.get("candidates", []) or []:
            try:
                await _create_candidate_from_appraisal(db, user_id, cand)
                stats["candidates"] += 1
            except Exception as e:
                logger.warning(f"[appraisal] candidate skipped ({e}): {cand}")

    # Consume regardless of what got applied — same rule as deliberation.py:
    # a batch that fails to produce anything usable must not re-trigger the
    # same observations forever.
    await consume_observations(user_id, [o.id for o in observations])

    await _write_run_log(user_id, stats, len(observations))

    logger.info(f"[appraisal] cycle complete: {stats} (from {len(observations)} observations)")
    return stats


async def _write_run_log(user_id: str, stats: Dict[str, Any], observation_count: int) -> None:
    """Write to agent_run_log (Phase 3.2 / §6 Phase 3 journal rule): this is
    what lets consolidation's existing daily journal synthesis (which
    already reads agent_run_log's `deliberation_history`) pick up appraisal
    activity without any change to consolidation.py itself — one more
    source feeding the same daily synthesis entry, not a second journal
    mechanism."""
    from sqlalchemy import text as sa_text
    from app.db.session import get_async_session_factory

    summary = (
        f"Appraisal cycle: {stats.get('brief_patches', 0)} brief patch(es), "
        f"{stats.get('candidates', 0)} candidate(s) from {observation_count} observation(s)."
    )
    try:
        factory = get_async_session_factory()
        async with factory() as db:
            await db.execute(sa_text("""
                INSERT INTO agent_run_log
                    (user_id, source, run_at, context_summary, actions_taken, created_at)
                VALUES
                    (:uid, 'appraisal', NOW(), :summary, CAST(:actions AS jsonb), NOW())
            """), {
                "uid": user_id,
                "summary": summary[:2000],
                "actions": json.dumps(stats),
            })
            await db.commit()
    except Exception as e:
        logger.warning(f"[appraisal] run_log write failed: {e}")
