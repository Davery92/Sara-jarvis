"""Moment cards (SARA_ALIVE §5.8/§5.9, 2026-07-31) — rare, minted cards Sara
surfaces once: a right-moment memory callback, or "I made you something"
when an artifact lands without David watching it happen. One table
(`moment_card`), one shape, two kinds — see the migration's own docstring
for why they share infrastructure instead of two parallel systems.

Both mints ride existing organs (memory.recall, the Artifact model) rather
than building new retrieval or generation paths, per the felt layer's own
rule ("riding existing organs, no new verticals").
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

_DAVID_USER_ID = get_owner_id()

# "Rare" per the plan's own word for this feature — at most one callback
# card in this many days, so it reads as a genuine right-moment surprise
# rather than a recurring nag.
_MIN_DAYS_BETWEEN_CALLBACKS = 5
_MIN_CALLBACK_AGE_DAYS = 21
_MIN_CALLBACK_SCORE = 0.55


async def maybe_mint_proof_of_memory_card(db: Session, user_id: str = _DAVID_USER_ID) -> Optional[str]:
    """Look for a genuine right-moment callback: something from David's own
    recent conversation that semantically echoes a much older memory. Mints
    at most one card per `_MIN_DAYS_BETWEEN_CALLBACKS` window. Returns the
    card's title if one was minted, else None (nothing worth surfacing, or
    the rate limit hasn't cleared — both are normal, not failures)."""
    from sqlalchemy import text as sql_text

    recent = db.execute(sql_text("""
        SELECT MAX(created_at) FROM moment_card
        WHERE user_id = :uid AND kind = 'proof_of_memory'
    """), {"uid": user_id}).scalar()
    if recent is not None:
        gap = db.execute(sql_text(
            "SELECT NOW() - :recent < (:days || ' days')::interval"
        ), {"recent": recent, "days": _MIN_DAYS_BETWEEN_CALLBACKS}).scalar()
        if gap:
            return None

    # Seed query: David's own words from the last day, as a real recent
    # theme to search an echo of — not a synthetic prompt.
    recent_row = db.execute(sql_text("""
        SELECT content FROM episode
        WHERE user_id = :uid AND role = 'user'
          AND created_at > NOW() - INTERVAL '24 hours'
          AND length(content) > 20
        ORDER BY created_at DESC LIMIT 1
    """), {"uid": user_id}).fetchone()
    if not recent_row:
        return None
    seed_text = recent_row[0]

    try:
        from app.services.memory_recall import recall
        result = await recall(user_id=user_id, query=seed_text, k=10,
                               kinds=["episode", "note", "summary"])
    except Exception as e:
        logger.debug(f"[moment_card] recall failed (skipping this cycle): {e}")
        return None

    import datetime as _dt
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=_MIN_CALLBACK_AGE_DAYS)
    candidates = []
    for trace in result.get("traces") or []:
        when = trace.get("when")
        if not when or trace.get("score", 0) < _MIN_CALLBACK_SCORE:
            continue
        try:
            when_dt = _dt.datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if when_dt.tzinfo is None:
            when_dt = when_dt.replace(tzinfo=_dt.timezone.utc)
        if when_dt < cutoff:
            candidates.append((trace, when_dt))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0].get("score", 0), reverse=True)
    old_trace, old_when = candidates[0]

    card = await _compose_callback_card(seed_text, old_trace["text"], old_when)
    if not card:
        return None

    db.execute(sql_text("""
        INSERT INTO moment_card (user_id, kind, title, body, source_ref, source_kind)
        VALUES (:uid, 'proof_of_memory', :title, :body, :ref, :kind)
    """), {
        "uid": user_id, "title": card["title"], "body": card["body"],
        "ref": old_trace.get("id"), "kind": old_trace.get("kind"),
    })
    db.commit()
    logger.info(f"[moment_card] minted proof-of-memory card: {card['title']}")
    return card["title"]


async def _compose_callback_card(recent_text: str, old_text: str, old_when) -> Optional[dict]:
    try:
        import httpx
        import json as _json
        from app.services.llm_broker import resolve as resolve_capability

        cap = resolve_capability("utility")
        when_str = old_when.strftime("%B %Y")
        prompt = (
            "David just said something that echoes an older memory. Write a short, warm, "
            "specific callback in Sara's own first-person voice — the kind of thing that makes "
            "someone feel truly known, not a data readout. One sentence, no more than 200 characters. "
            "If the connection is actually weak or generic, say so honestly by returning null.\n\n"
            f"What David just said: {recent_text[:400]}\n\n"
            f"Old memory (from {when_str}): {old_text[:400]}\n\n"
            "Return ONLY valid JSON: {\"title\": \"short label, 4-8 words\", \"body\": \"the callback sentence\"} "
            "or {\"title\": null, \"body\": null} if the connection isn't genuinely worth surfacing."
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{cap['base_url']}/chat/completions",
                json={
                    "model": cap["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 200,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        parsed = _json.loads(content.strip())
        if not parsed.get("title") or not parsed.get("body"):
            return None
        return parsed
    except Exception as e:
        logger.debug(f"[moment_card] callback composition failed: {e}")
        return None


async def mint_artifact_unwrap_cards(db: Session, user_id: str = _DAVID_USER_ID, lookback_hours: int = 6) -> int:
    """"Sara made you something": an artifact that landed without David
    watching it happen (no conversation_id — a background/dreaming job made
    it, not a live chat turn) gets a card instead of just sitting in Studio
    unnoticed. Idempotent: only artifacts with no existing card yet.
    Returns how many cards were minted this pass."""
    from sqlalchemy import text as sql_text

    rows = db.execute(sql_text("""
        SELECT a.id, a.title, a.artifact_type
        FROM artifacts a
        WHERE a.user_id = :uid
          AND a.conversation_id IS NULL
          AND a.created_at > NOW() - (:hours || ' hours')::interval
          AND NOT EXISTS (
              SELECT 1 FROM moment_card mc
              WHERE mc.kind = 'artifact_unwrap' AND mc.source_ref = a.id::text
          )
        ORDER BY a.created_at DESC
        LIMIT 5
    """), {"uid": user_id, "hours": lookback_hours}).fetchall()

    minted = 0
    for artifact_id, title, artifact_type in rows:
        why = await _compose_unwrap_why(title, artifact_type)
        db.execute(sql_text("""
            INSERT INTO moment_card (user_id, kind, title, body, source_ref, source_kind)
            VALUES (:uid, 'artifact_unwrap', :title, :body, :ref, 'artifact')
        """), {
            "uid": user_id, "title": "Sara made you something",
            "body": why or f"A new {artifact_type}: \"{title}\".",
            "ref": str(artifact_id),
        })
        minted += 1
    if minted:
        db.commit()
        logger.info(f"[moment_card] minted {minted} artifact-unwrap card(s)")
    return minted


async def _compose_unwrap_why(title: str, artifact_type: str) -> Optional[str]:
    try:
        import httpx
        import json as _json
        from app.services.llm_broker import resolve as resolve_capability

        cap = resolve_capability("utility")
        prompt = (
            f"Sara made David a {artifact_type} called \"{title}\" on her own, without him asking in "
            "the moment. Write one short first-person sentence (under 140 characters) explaining why "
            "she made it — warm, specific, not corporate. "
            "Return ONLY valid JSON: {\"why\": \"...\"}"
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{cap['base_url']}/chat/completions",
                json={
                    "model": cap["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.5,
                    "max_tokens": 120,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        parsed = _json.loads(content.strip())
        return parsed.get("why")
    except Exception as e:
        logger.debug(f"[moment_card] unwrap-why composition failed: {e}")
        return None
