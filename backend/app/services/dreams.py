"""Real dreaming (§3.8) — the 2 AM slot earns its name.

Three offline jobs, none user-facing directly, all bounded (≤1 local-Qwen call
each, local-first, read-only):

1. **Counterfactual replay** — for the week's prediction misses and late-caught
   problems, ask "what signal existed earlier, what monitor would have caught
   it?" → a proposed canary, surfaced as a low-key self-note (not auto-applied).
2. **Rehearsal** — simulate tomorrow against rhythm + calendar + readiness; where
   are the conflicts? → pre-staged note for the morning.
3. **Recombination** — sample distant-but-related PKG pairs in embedding space,
   LLM-judge for a real connection, surface at most ONE survivor/day as a
   low-confidence morning intuition.

Everything lands in `sara_journal` (entry_type='dream'). The morning brief and
the workspace can surface them; nothing pushes.
"""
import json
import logging
import uuid

from sqlalchemy import text

logger = logging.getLogger(__name__)

_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


async def _qwen(system: str, user: str, max_tokens: int = 300) -> str:
    from app.core.llm import get_background_llm_client
    client = get_background_llm_client()
    resp = await client.chat_completion(
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.6, max_tokens=max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    if isinstance(resp, dict):
        ch = resp.get("choices", [])
        if ch:
            return (ch[0].get("message", {}).get("content", "") or "").strip()
    return str(resp).strip()


async def _journal(db, content: str, watching_for: str = None):
    await db.execute(text("""
        INSERT INTO sara_journal (id, user_id, entry_type, content, watching_for, created_at)
        VALUES (:id, :u, 'dream', :c, :w, NOW())
    """), {"id": str(uuid.uuid4()), "u": _DAVID, "c": content, "w": watching_for})


async def counterfactual_replay(db) -> dict:
    """What earlier signal would have caught this week's misses?"""
    misses = (await db.execute(text("""
        SELECT statement, matched_value FROM prediction
        WHERE outcome = 'violated' AND resolved_at >= NOW() - INTERVAL '7 days'
        ORDER BY confidence DESC LIMIT 8
    """))).fetchall()
    fails = (await db.execute(text("""
        SELECT task_name, error_class, occurrences FROM task_failure
        WHERE last_seen >= NOW() - INTERVAL '7 days'
        ORDER BY occurrences DESC LIMIT 5
    """))).fetchall()
    if not misses and not fails:
        return {"effect": "nothing_to_replay"}

    evidence = []
    for m in misses:
        evidence.append(f"- Missed prediction: {m.statement}")
    for f in fails:
        evidence.append(f"- Task failure: {f.task_name} ({f.error_class}, x{f.occurrences})")

    finding = await _qwen(
        "You are Sara, replaying this week's surprises to learn. Be concrete.",
        "Here are things I got wrong or caught late this week:\n\n"
        + "\n".join(evidence)
        + "\n\nIn 2-3 sentences: what earlier, observable signal existed that I "
        "could monitor to catch this class of problem sooner next time?",
    )
    await _journal(db, f"Counterfactual replay: {finding}", watching_for=finding[:200])
    await db.commit()
    logger.info(f"🌙 Counterfactual replay: {finding[:70]!r}")
    return {"effect": "replayed", "finding": finding}


async def rehearsal(db) -> dict:
    """Simulate tomorrow against calendar + readiness; surface conflicts."""
    events = (await db.execute(text("""
        SELECT title, start_time FROM calendar_event
        WHERE user_id = :u AND COALESCE(all_day, FALSE) = FALSE
          AND start_time >= NOW() AND start_time < NOW() + INTERVAL '36 hours'
        ORDER BY start_time ASC LIMIT 10
    """), {"u": _DAVID})).fetchall()
    readiness = (await db.execute(text("""
        SELECT score FROM morning_readiness WHERE user_id = :u
        ORDER BY created_at DESC LIMIT 1
    """), {"u": _DAVID})).scalar()
    if not events:
        return {"effect": "no_tomorrow_events"}

    ev_lines = "\n".join(f"- {e.title} at {e.start_time}" for e in events)
    r_txt = f"Recovery/readiness is {readiness}." if readiness is not None else "Readiness unknown."
    finding = await _qwen(
        "You are Sara, quietly rehearsing David's tomorrow to pre-empt friction. Be practical.",
        f"Tomorrow's schedule:\n{ev_lines}\n\n{r_txt}\n\n"
        "In 2-3 sentences, what's the one friction point to pre-empt (a meeting "
        "over his usual lunch, a dense morning on low recovery, back-to-backs "
        "with no gap)? If it looks smooth, say so.",
    )
    await _journal(db, f"Tomorrow rehearsal: {finding}", watching_for=finding[:200])
    await db.commit()
    logger.info(f"🌙 Rehearsal: {finding[:70]!r}")
    return {"effect": "rehearsed", "finding": finding}


async def recombination(db) -> dict:
    """Find a distant-but-related PKG pair and judge whether it's a real, useful
    connection. Surface at most one/day as a low-confidence intuition."""
    # Medium cosine distance = related but not obvious. Subquery avoids having to
    # serialize the seed vector as a bind param (pgvector <=> is cosine distance).
    pair = (await db.execute(text("""
        WITH seed AS (
            SELECT pkg_id, content_text, embedding FROM pkg_embedding
            WHERE embedding IS NOT NULL ORDER BY RANDOM() LIMIT 1
        )
        SELECT s.content_text AS a, n.content_text AS b,
               (n.embedding <=> s.embedding) AS dist
        FROM seed s, pkg_embedding n
        WHERE n.pkg_id != s.pkg_id AND n.embedding IS NOT NULL
          AND (n.embedding <=> s.embedding) BETWEEN 0.35 AND 0.62
        ORDER BY (n.embedding <=> s.embedding) ASC
        LIMIT 1
    """))).first()
    if not pair:
        return {"effect": "no_pair_found"}

    verdict = await _qwen(
        "You are Sara, half-dreaming, looking for non-obvious connections. Be honest: "
        "most random pairs are NOT meaningfully connected. Only flag a real one.",
        f"Two things I know:\nA: {pair.a[:300]}\nB: {pair.b[:300]}\n\n"
        "Is there a genuine, non-obvious, useful connection between these? "
        "If yes, state it in ONE sentence starting 'Connection:'. "
        "If no (be strict), reply exactly 'No connection.'",
    )
    if "no connection" in verdict.lower() or not verdict.lower().startswith("connection"):
        return {"effect": "no_real_connection"}

    await _journal(db, f"Morning intuition (low confidence): {verdict}", watching_for="recombination")
    await db.commit()
    logger.info(f"🌙 Recombination surfaced an intuition: {verdict[:70]!r}")
    return {"effect": "intuition", "intuition": verdict}


async def run_dream_cycle(db) -> dict:
    """Run all three dream jobs. Failures in one never block the others."""
    out = {}
    for name, fn in (("counterfactual", counterfactual_replay),
                     ("rehearsal", rehearsal),
                     ("recombination", recombination)):
        try:
            out[name] = await fn(db)
        except Exception as e:
            logger.warning(f"dream job {name} failed: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            out[name] = {"effect": "error", "error": str(e)}
    return out
