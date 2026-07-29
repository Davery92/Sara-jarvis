"""Intrinsic motivation / curiosity (§3.5) — Sara generates her own goals.

She generates goals from well-defined sources, pursues them with existing
machinery, and reports what she learned:
  1. **Repeated prediction errors** — a domain where she keeps being wrong is a
     domain she doesn't understand (uses the §3.2 prediction loop).
  2. **Calibration gaps** — where her stated confidence far exceeds her actual
     hit-rate (§3.9), she's overconfident and doesn't really understand it.

A nightly selector promotes the single best candidate (budget: ≤1 active
curiosity goal, ≤1 investigation LLM call/day), pursues it via a bounded
local-Qwen investigation over data Sara already has (local-first policy — no
frontier model, read-only), and lands the result as a "what I learned" journal
entry. NOT autonomous feature-development, NOT self-modification, NOT unbounded
spend — the budget and the read-only effector are the whole point.
"""
import json
import logging
import uuid
from typing import Dict, Any, List, Optional

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Budget.
_MAX_ACTIVE_CURIOSITY_GOALS = 1
_MIN_VIOLATIONS_FOR_GOAL = 5     # a domain must miss repeatedly to be interesting
_CALIBRATION_GAP_THRESHOLD = 0.35  # stated conf − hit_rate this big = overconfident


async def pursued_today(db, user_id: str = _DAVID) -> bool:
    """Arc 4.3: the daily budget (≤1 investigation LLM call/day) used to be
    enforced structurally — `run_curiosity` only ever ran once, on its own
    nightly schedule. Now that pursuit is triggered by *any* ambient wake
    that finds no David-work (not a fixed schedule), the budget needs its
    own explicit check: a goal already active, or completed today, means
    don't pursue again until tomorrow."""
    row = (await db.execute(text("""
        SELECT 1 FROM sara_goal
        WHERE created_by = 'curiosity'
          AND (status = 'active' OR (status = 'completed' AND completed_at::date = CURRENT_DATE))
        LIMIT 1
    """))).first()
    return row is not None


async def generate_candidates(db, user_id: str = _DAVID) -> dict:
    """Mint candidate curiosity goals from prediction errors + calibration gaps."""
    minted = 0

    # Skip domains already in flight (candidate/active) OR investigated in the
    # last 7 days (don't re-investigate the same domain nightly — anti-repetition).
    existing = (await db.execute(text("""
        SELECT plan->>'domain' FROM sara_goal
        WHERE created_by = 'curiosity'
          AND (status IN ('candidate', 'active')
               OR (status = 'completed' AND completed_at >= NOW() - INTERVAL '7 days'))
    """))).fetchall()
    busy_domains = {r[0] for r in existing if r[0]}

    # Source 1: prediction-error clusters (last 14 days).
    clusters = (await db.execute(text("""
        SELECT domain, COUNT(*) AS misses
        FROM prediction
        WHERE user_id = :u AND outcome = 'violated'
          AND resolved_at >= NOW() - INTERVAL '14 days'
        GROUP BY domain
        HAVING COUNT(*) >= :minv
        ORDER BY misses DESC
    """), {"u": user_id, "minv": _MIN_VIOLATIONS_FOR_GOAL})).fetchall()

    for domain, misses in clusters:
        if not domain or domain in busy_domains:
            continue
        title = f"Understand why my {domain} predictions keep missing"
        why = (f"I've been wrong about {domain} {misses} times in two weeks. "
               f"A domain I keep mispredicting is one I don't actually understand yet.")
        await _mint_goal(db, user_id, title, why, {"domain": domain, "source": "prediction_errors", "misses": misses})
        busy_domains.add(domain)
        minted += 1

    await db.commit()
    logger.info(f"🧭 Curiosity: minted {minted} candidate goal(s)")
    return {"effect": "generated_candidates", "minted": minted}


async def _mint_goal(db, user_id, title, why, plan):
    await db.execute(text("""
        INSERT INTO sara_goal (id, title, why, created_by, status, plan, created_at)
        VALUES (:id, :title, :why, 'curiosity', 'candidate', CAST(:plan AS jsonb), NOW())
    """), {"id": str(uuid.uuid4()), "title": title, "why": why, "plan": json.dumps(plan)})


async def select_and_pursue(db, user_id: str = _DAVID) -> dict:
    """Nightly: if budget allows, promote the best candidate and investigate it."""
    active = (await db.execute(text("""
        SELECT COUNT(*) FROM sara_goal
        WHERE created_by = 'curiosity' AND status = 'active'
    """))).scalar() or 0
    if active >= _MAX_ACTIVE_CURIOSITY_GOALS:
        return {"effect": "budget_full", "active": active}

    cand = (await db.execute(text("""
        SELECT id::text, title, why, plan FROM sara_goal
        WHERE created_by = 'curiosity' AND status = 'candidate'
        ORDER BY COALESCE((plan->>'misses')::int, 0) DESC, created_at ASC
        LIMIT 1
    """))).first()
    if not cand:
        return {"effect": "no_candidates"}

    goal_id, title, why, plan = cand
    plan = plan if isinstance(plan, dict) else json.loads(plan or "{}")
    domain = plan.get("domain")

    await db.execute(text(
        "UPDATE sara_goal SET status='active', last_progress_at=NOW() WHERE id = CAST(:id AS uuid)"
    ), {"id": goal_id})
    await db.commit()

    # Pursue: bounded investigation over Sara's own data.
    finding = await _investigate(db, user_id, domain)

    await db.execute(text("""
        UPDATE sara_goal
        SET status='completed', outcome=:o, completed_at=NOW(), last_progress_at=NOW()
        WHERE id = CAST(:id AS uuid)
    """), {"o": finding, "id": goal_id})
    await _write_journal(db, user_id, domain, finding)
    await db.commit()

    logger.info(f"🧭 Curiosity: pursued '{title}' → {finding[:80]!r}")
    return {"effect": "pursued", "goal_id": goal_id, "domain": domain, "finding": finding}


async def _investigate(db, user_id: str, domain: str) -> str:
    """Cross-reference the domain's recent misses and ask local Qwen for the
    likely explanation. One LLM call, read-only, local-first."""
    misses = (await db.execute(text("""
        SELECT statement, predicted_value, matched_value, window_start
        FROM prediction
        WHERE user_id = :u AND domain = :d AND outcome = 'violated'
          AND resolved_at >= NOW() - INTERVAL '14 days'
        ORDER BY resolved_at DESC LIMIT 12
    """), {"u": user_id, "d": domain})).fetchall()

    if not misses:
        return f"No recent {domain} misses to investigate — the pattern may have resolved itself."

    lines = []
    for m in misses:
        pv = m.predicted_value if isinstance(m.predicted_value, dict) else {}
        mv = m.matched_value if isinstance(m.matched_value, dict) else {}
        lines.append(f"- Expected: {m.statement}. Actual: {json.dumps(mv)[:120]}")
    evidence = "\n".join(lines)

    prompt = (
        f"I keep mispredicting things in the '{domain}' domain. Here are my recent misses:\n\n"
        f"{evidence}\n\n"
        "In 2-3 sentences, what's the most likely explanation for why my predictions "
        "in this domain are wrong? Be concrete and specific. If the pattern simply "
        "shifted (e.g. a routine now happens at a different time), say so plainly."
    )
    try:
        from app.core.llm import get_background_llm_client
        client = get_background_llm_client()
        resp = await client.chat_completion(
            messages=[
                {"role": "system", "content": "You are Sara, reflecting on your own prediction errors. Be honest and concrete."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5, max_tokens=300,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        content = ""
        if isinstance(resp, dict):
            ch = resp.get("choices", [])
            if ch:
                content = ch[0].get("message", {}).get("content", "")
        else:
            content = str(resp)
        return (content or "").strip() or f"Investigated {domain} but couldn't form a clear conclusion."
    except Exception as e:
        logger.warning(f"curiosity investigation LLM failed: {e}")
        return (f"I noticed I keep missing {domain} predictions ({len(misses)} times), "
                "but couldn't complete the analysis this time.")


async def _write_journal(db, user_id: str, domain: str, finding: str):
    try:
        await db.execute(text("""
            INSERT INTO sara_journal (id, user_id, entry_type, content, created_at)
            VALUES (:id, :u, 'curiosity', :c, NOW())
        """), {"id": str(uuid.uuid4()), "u": user_id,
               "c": f"Followed my curiosity about {domain}. What I figured out: {finding}"})
    except Exception as e:
        logger.debug(f"curiosity journal write skipped: {e}")
