"""
ACS Mode Selector — two-phase cognitive mode selection.

Phase 1: Compute heuristic signals from the interest graph and session history.
Phase 2: LLM decision using those signals.
"""

import json
import logging
from typing import Optional

from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cognitive modes
MODE_EXPLORATION = "exploration"
MODE_CONSOLIDATION = "consolidation"
MODE_REFLECTION = "reflection"
MODE_EXECUTION = "execution"

VALID_MODES = {MODE_EXPLORATION, MODE_CONSOLIDATION, MODE_REFLECTION, MODE_EXECUTION}

# Default durations per mode (minutes)
MODE_DURATIONS = {
    MODE_EXPLORATION: 60,
    MODE_CONSOLIDATION: 45,
    MODE_REFLECTION: 30,
    MODE_EXECUTION: 90,
}


async def _compute_signals(user_id: str) -> dict:
    """Phase 1: Compute heuristic signals from the interest graph and session logs."""
    from app.db.session import get_async_session_factory
    from app.services.acs.interest_graph import InterestGraph

    graph = InterestGraph()
    async_session = get_async_session_factory()

    signals = {
        "exploration_signal": 0.5,
        "consolidation_signal": 0.5,
        "reflection_signal": 0.5,
        "bridge_opportunities": 0,
        "last_3_modes": [],
        "total_active_nodes": 0,
        "pending_david_requests": 0,
        "recent_primary_topics": [],
        "repeat_topic_streak": 0,
    }

    async with async_session() as db:
        # Count active nodes
        result = await db.execute(text("""
            SELECT COUNT(*) FROM acs_interest_node
            WHERE user_id = :uid AND status = 'active'
        """), {"uid": user_id})
        total_active = result.scalar() or 0
        signals["total_active_nodes"] = total_active

        if total_active > 0:
            # Exploration signal: high-fascination / low-depth nodes
            result = await db.execute(text("""
                SELECT COUNT(*) FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                  AND fascination > 0.4 AND depth < 0.3
            """), {"uid": user_id})
            frontier = result.scalar() or 0
            signals["exploration_signal"] = frontier / total_active

            # David-requested nodes with low depth — strong exploration driver
            result = await db.execute(text("""
                SELECT COUNT(*) FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                  AND source = 'david_request' AND depth < 0.5
            """), {"uid": user_id})
            pending_david = result.scalar() or 0
            signals["pending_david_requests"] = pending_david

            # Consolidation signal: unconnected nodes added in last 72h
            result = await db.execute(text("""
                SELECT COUNT(*) FROM acs_interest_node n
                WHERE n.user_id = :uid AND n.status = 'active'
                  AND n.created_at > NOW() - INTERVAL '72 hours'
                  AND NOT EXISTS (
                      SELECT 1 FROM acs_interest_edge e
                      WHERE e.source_node_id = n.id OR e.target_node_id = n.id
                  )
            """), {"uid": user_id})
            unconnected_recent = result.scalar() or 0
            signals["consolidation_signal"] = min(1.0, unconnected_recent / max(total_active, 1))

        # Reflection signal: days since last reflection session
        result = await db.execute(text("""
            SELECT started_at FROM acs_session_log
            WHERE user_id = :uid AND mode = 'reflection'
            ORDER BY started_at DESC
            LIMIT 1
        """), {"uid": user_id})
        row = result.fetchone()
        if row and row[0]:
            from datetime import datetime, timezone
            last_reflection = row[0]
            if last_reflection.tzinfo is None:
                last_reflection = last_reflection.replace(tzinfo=timezone.utc)
            days_since = (datetime.now(timezone.utc) - last_reflection).total_seconds() / 86400
            signals["reflection_signal"] = min(1.0, days_since / 7)  # Maxes out at 7 days
        else:
            signals["reflection_signal"] = 1.0  # Never reflected → high signal

        # Last 3 modes
        result = await db.execute(text("""
            SELECT mode FROM acs_session_log
            WHERE user_id = :uid AND mode IS NOT NULL
            ORDER BY started_at DESC
            LIMIT 3
        """), {"uid": user_id})
        signals["last_3_modes"] = [r[0] for r in result.fetchall()]

        result = await db.execute(text("""
            SELECT primary_topic
            FROM acs_session_log
            WHERE user_id = :uid
              AND primary_topic IS NOT NULL
              AND primary_topic != ''
            ORDER BY started_at DESC
            LIMIT 3
        """), {"uid": user_id})
        recent_topics = [r[0] for r in result.fetchall() if r[0]]
        signals["recent_primary_topics"] = recent_topics
        if recent_topics:
            streak = 1
            lead_topic = recent_topics[0]
            for topic in recent_topics[1:]:
                if topic == lead_topic:
                    streak += 1
                else:
                    break
            signals["repeat_topic_streak"] = streak

    # Bridge opportunities
    try:
        bridges = await graph.find_bridge_opportunities(user_id, limit=10)
        signals["bridge_opportunities"] = len(bridges)
    except Exception as e:
        logger.debug(f"Bridge opportunity check failed: {e}")

    # Topic diversity: detect if recent sessions are all on the same topic cluster
    try:
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT DISTINCT unnest(string_to_array(
                    COALESCE(sl.summary, ''), ' '
                )) FROM acs_session_log sl
                WHERE sl.user_id = :uid
                  AND sl.started_at > NOW() - INTERVAL '24 hours'
                  AND sl.mode = 'exploration'
                LIMIT 1
            """), {"uid": user_id})
            # Simpler approach: count distinct exploration topics in last 24h
            result = await db.execute(text("""
                SELECT COUNT(DISTINCT n.folder_id) as distinct_folders,
                       COUNT(*) as total_notes
                FROM note n
                JOIN folder f ON n.folder_id = f.id
                WHERE n.user_id = :uid
                  AND n.created_at > NOW() - INTERVAL '24 hours'
                  AND f.name NOT LIKE 'Journal%'
                  AND f.name NOT LIKE 'Logs%'
                  AND f.name NOT LIKE 'Daily Plans%'
            """), {"uid": user_id})
            row = result.fetchone()
            if row and row[1] >= 5:  # At least 5 notes in 24h
                distinct_folders = row[0] or 1
                total_notes = row[1]
                # If writing lots of notes but all in 1-2 folders → low diversity
                diversity_ratio = distinct_folders / total_notes
                signals["topic_diversity"] = diversity_ratio
                if diversity_ratio < 0.15:  # Less than 15% folder variety
                    signals["topic_saturation"] = True
    except Exception as e:
        logger.debug(f"Topic diversity check failed: {e}")

    # Calendar awareness: busy schedule → prefer shorter consolidation
    try:
        from datetime import datetime, timezone, timedelta
        from app.db.session import get_async_session_factory as _get_sf
        _sf = _get_sf()
        async with _sf() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(text("""
                SELECT COUNT(*) FROM calendar_event
                WHERE user_id = :uid
                  AND start_time >= :now
                  AND start_time <= :until
                  AND is_completed = FALSE
            """), {"uid": user_id, "now": now, "until": now + timedelta(hours=24)})
            events_24h = result.scalar() or 0
            signals["calendar_events_24h"] = events_24h

            if events_24h >= 5:
                # Busy day — boost consolidation (shorter sessions)
                signals["consolidation_signal"] = min(1.0, signals["consolidation_signal"] + 0.2)
            elif events_24h <= 1:
                # Free day — boost exploration
                signals["exploration_signal"] = min(1.0, signals["exploration_signal"] + 0.1)
    except Exception as e:
        logger.debug(f"Calendar signal check failed: {e}")

    # Mode effectiveness: learn from recent session outcomes per mode
    try:
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT cognitive_mode,
                       AVG(turns_completed) AS avg_turns,
                       AVG(notes_created) AS avg_notes,
                       COUNT(*) FILTER (WHERE end_reason = 'error') AS errors,
                       COUNT(*) AS total
                FROM acs_session
                WHERE user_id = :uid
                  AND started_at > NOW() - INTERVAL '14 days'
                  AND cognitive_mode IS NOT NULL
                GROUP BY cognitive_mode
            """), {"uid": user_id})
            mode_effectiveness = {}
            for row in result.fetchall():
                mode, avg_turns, avg_notes, errors, total = row
                if total >= 2:
                    # Effectiveness = combination of productivity and reliability
                    productivity = min(1.0, (avg_notes or 0) / 10)  # Normalize: 10 notes = max
                    reliability = 1.0 - (errors / total)
                    mode_effectiveness[mode] = round(0.6 * productivity + 0.4 * reliability, 2)
            if mode_effectiveness:
                signals["mode_effectiveness"] = mode_effectiveness
    except Exception as e:
        logger.debug(f"Mode effectiveness check failed: {e}")

    return signals


async def _get_next_plan_item(user_id: str) -> Optional[dict]:
    """Get the highest-priority pending plan item for today."""
    from app.db.session import get_async_session_factory
    from datetime import date

    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT id, title, description, success_criteria, priority, source,
                   estimated_turns, cognitive_mode
            FROM acs_plan_item
            WHERE user_id = :uid AND plan_date = :today
              AND status IN ('pending', 'deferred', 'blocked', 'in_progress')
              AND status != 'parked'
              AND (reopen_after IS NULL OR reopen_after <= NOW())
              AND (
                  status != 'in_progress'
                  OR assigned_session_id IS NULL
              )
              AND (
                  source = 'david_chat'
                  OR COALESCE(revisit_count, 0) < 3
              )
              AND (depends_on IS NULL OR depends_on IN (
                  SELECT id FROM acs_plan_item
                  WHERE user_id = :uid AND status = 'completed'
              ))
            ORDER BY
              CASE WHEN source = 'david_chat' THEN 0 ELSE 1 END,
              CASE status
                WHEN 'pending' THEN 0
                WHEN 'deferred' THEN 1
                WHEN 'blocked' THEN 2
                WHEN 'in_progress' THEN 3
                ELSE 4
              END,
              (priority - COALESCE(revisit_count, 0) * 8) DESC,
              created_at ASC
            LIMIT 1
        """), {"uid": user_id, "today": date.today()})
        row = result.fetchone()
        if row:
            return {
                "id": row[0], "title": row[1], "description": row[2],
                "success_criteria": row[3], "priority": row[4], "source": row[5],
                "estimated_turns": row[6], "cognitive_mode": row[7],
            }
    return None


async def claim_plan_item(
    user_id: str,
    session_id: str,
    preferred_plan_item_id: Optional[str] = None,
) -> Optional[dict]:
    """Atomically claim the next eligible plan item for a session."""
    from app.db.session import get_async_session_factory
    from datetime import date

    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text("""
            WITH candidate AS (
                SELECT id
                FROM acs_plan_item
                WHERE user_id = :uid
                  AND plan_date = :today
                  AND status IN ('pending', 'deferred', 'blocked', 'in_progress')
                  AND status != 'parked'
                  AND (reopen_after IS NULL OR reopen_after <= NOW())
                  AND (
                      status != 'in_progress'
                      OR assigned_session_id IS NULL
                      OR assigned_session_id = :sid
                  )
                  AND (
                      source = 'david_chat'
                      OR COALESCE(revisit_count, 0) < 3
                  )
                  AND (depends_on IS NULL OR depends_on IN (
                      SELECT id FROM acs_plan_item
                      WHERE user_id = :uid AND status = 'completed'
                  ))
                ORDER BY
                  CASE
                    WHEN CAST(:preferred_id AS VARCHAR) IS NOT NULL AND id = CAST(:preferred_id AS VARCHAR) THEN 0
                    ELSE 1
                  END,
                  CASE WHEN source = 'david_chat' THEN 0 ELSE 1 END,
                  CASE status
                    WHEN 'pending' THEN 0
                    WHEN 'deferred' THEN 1
                    WHEN 'blocked' THEN 2
                    WHEN 'in_progress' THEN 3
                    ELSE 4
                  END,
                  (priority - COALESCE(revisit_count, 0) * 8) DESC,
                  created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE acs_plan_item p
            SET status = 'in_progress',
                assigned_session_id = :sid,
                started_at = COALESCE(started_at, NOW()),
                updated_at = NOW(),
                revisit_count = COALESCE(p.revisit_count, 0)
                    + CASE
                        WHEN p.status IN ('deferred', 'blocked', 'in_progress') THEN 1
                        ELSE 0
                      END
            FROM candidate
            WHERE p.id = candidate.id
            RETURNING p.id, p.title, p.description, p.success_criteria, p.priority,
                      p.source, p.estimated_turns, p.cognitive_mode, p.revisit_count
        """), {
            "uid": user_id,
            "today": date.today(),
            "sid": session_id,
            "preferred_id": preferred_plan_item_id,
        })
        row = result.fetchone()
        await db.commit()
        if not row:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "success_criteria": row[3],
            "priority": row[4],
            "source": row[5],
            "estimated_turns": row[6],
            "cognitive_mode": row[7],
            "revisit_count": row[8],
        }


async def _recent_execution_ratio(user_id: str, window: int = 5) -> float:
    """What fraction of the last N sessions were execution mode?"""
    from app.db.session import get_async_session_factory

    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT mode FROM acs_session_log
            WHERE user_id = :uid AND mode IS NOT NULL
            ORDER BY started_at DESC
            LIMIT :window
        """), {"uid": user_id, "window": window})
        modes = [r[0] for r in result.fetchall()]
    if not modes:
        return 0.0
    return sum(1 for m in modes if m == "execution") / len(modes)


async def select_mode(user_id: str) -> tuple[str, Optional[str]]:
    """Select the cognitive mode for the next ACS session.

    Returns (mode, plan_item_id) where plan_item_id is set for execution mode.
    Defaults to ('exploration', None) on any failure.
    """
    signals: Optional[dict] = None

    # Phase 0: Check for pending plan items
    try:
        next_item = await _get_next_plan_item(user_id)
        if next_item:
            # David's requests always get execution mode regardless of ratio
            if next_item["source"] == "david_chat" or next_item["priority"] >= 85:
                logger.info(
                    f"Execution mode (high priority): plan item "
                    f"'{next_item['title'][:60]}' (p={next_item['priority']})"
                )
                return MODE_EXECUTION, next_item["id"]

            signals = await _compute_signals(user_id)
            if (
                signals.get("repeat_topic_streak", 0) >= 2
                and next_item["title"] in signals.get("recent_primary_topics", [])
            ):
                logger.info(
                    f"Skipping execution for repeated topic '{next_item['title'][:60]}' "
                    "to force a loop break"
                )
                next_item = None

        if next_item:
            # For normal items, use soft ratio check — the closer to the limit,
            # the less likely we pick execution, but it's probabilistic not a hard wall
            recent_ratio = await _recent_execution_ratio(user_id, window=5)
            max_ratio = getattr(settings, 'acs_execution_ratio', 0.7)
            if recent_ratio < max_ratio:
                logger.info(
                    f"Execution mode: plan item '{next_item['title'][:60]}' "
                    f"(ratio {recent_ratio:.2f}/{max_ratio})"
                )
                return MODE_EXECUTION, next_item["id"]
            else:
                logger.info(
                    f"Execution ratio {recent_ratio:.2f} >= {max_ratio}, "
                    f"free session (next item: '{next_item['title'][:40]}')"
                )
    except Exception as e:
        logger.warning(f"Plan item check failed: {e}")

    # Consistency check: prose plan exists but no plan_items for today
    try:
        import os
        import redis.asyncio as aioredis
        from datetime import date
        _redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _r = await aioredis.from_url(_redis_url, decode_responses=True)
        try:
            _plan_key = f"sara:acs:daily_plan:{user_id}"
            _prose_exists = await _r.exists(_plan_key)
            if _prose_exists:
                from app.db.session import get_async_session_factory
                _as = get_async_session_factory()
                async with _as() as _db:
                    _count_result = await _db.execute(text("""
                        SELECT COUNT(*) FROM acs_plan_item
                        WHERE user_id = :uid AND plan_date = :today AND status != 'parked'
                    """), {"uid": user_id, "today": date.today()})
                    _item_count = _count_result.scalar() or 0
                if _item_count == 0:
                    _guard_key = f"sara:acs:planner_inconsistency_logged:{user_id}:{date.today().isoformat()}"
                    if not await _r.exists(_guard_key):
                        logger.error(
                            f"ACS mode_selector: prose daily plan exists in Redis but 0 plan_items "
                            f"for today — planner extraction likely failed silently"
                        )
                        await _r.set(_guard_key, "1", ex=86400)
        finally:
            if hasattr(_r, "aclose"):
                await _r.aclose()
            else:
                await _r.close()
    except Exception as e:
        logger.debug(f"Planner consistency check failed: {e}")

    # Phase 1: Compute signals (existing)
    if signals is None:
        try:
            signals = await _compute_signals(user_id)
        except Exception as e:
            logger.error(f"Mode signal computation failed: {e}")
            return MODE_EXPLORATION, None

    # Check mode repeat limit
    last_modes = signals.get("last_3_modes", [])
    max_repeat = settings.acs_v2_mode_max_repeat
    blocked_modes = set()
    if len(last_modes) >= max_repeat:
        for mode in VALID_MODES:
            if all(m == mode for m in last_modes[:max_repeat]):
                blocked_modes.add(mode)

    # Phase 2: LLM decision
    try:
        mode = await _llm_select_mode(signals, blocked_modes)
        if mode in VALID_MODES and mode not in blocked_modes:
            return mode, None
    except Exception as e:
        logger.warning(f"LLM mode selection failed, using heuristic fallback: {e}")

    # Heuristic fallback
    return _heuristic_fallback(signals, blocked_modes), None


def _heuristic_fallback(signals: dict, blocked_modes: set) -> str:
    """Simple heuristic mode selection as fallback."""
    candidates = [
        (MODE_EXPLORATION, signals.get("exploration_signal", 0)),
        (MODE_CONSOLIDATION, signals.get("consolidation_signal", 0)),
        (MODE_REFLECTION, signals.get("reflection_signal", 0)),
    ]

    # Apply mode effectiveness learning: boost modes that have been productive
    mode_eff = signals.get("mode_effectiveness", {})
    for i, (mode, score) in enumerate(candidates):
        eff = mode_eff.get(mode)
        if eff is not None:
            candidates[i] = (mode, score + eff * 0.2)  # Up to +0.2 for 100% effective

    # Boost consolidation if many bridge opportunities (mild)
    if signals.get("bridge_opportunities", 0) >= 5:
        candidates[1] = (MODE_CONSOLIDATION, candidates[1][1] + 0.15)

    # Strong boost for exploration when David has requested topics
    pending_david = signals.get("pending_david_requests", 0)
    if pending_david > 0:
        candidates[0] = (MODE_EXPLORATION, candidates[0][1] + 0.5)

    # If topic saturation detected, boost consolidation (to merge dupes) and
    # reflection (to step back) — discourage more exploration of the same thing
    if signals.get("topic_saturation"):
        candidates[0] = (MODE_EXPLORATION, candidates[0][1] - 0.3)
        candidates[1] = (MODE_CONSOLIDATION, candidates[1][1] + 0.3)
        candidates[2] = (MODE_REFLECTION, candidates[2][1] + 0.2)

    if signals.get("repeat_topic_streak", 0) >= 2:
        candidates[0] = (MODE_EXPLORATION, candidates[0][1] + 0.25)
        candidates[2] = (MODE_REFLECTION, candidates[2][1] + 0.2)
        candidates[1] = (MODE_CONSOLIDATION, candidates[1][1] - 0.1)

    # Sort by score descending
    candidates.sort(key=lambda x: x[1], reverse=True)

    for mode, _ in candidates:
        if mode not in blocked_modes:
            return mode

    return MODE_EXPLORATION


async def _llm_select_mode(signals: dict, blocked_modes: set) -> str:
    """Ask the LLM to select a mode based on signals."""
    from app.core.llm import BackgroundLLMClient

    blocked_str = ""
    if blocked_modes:
        blocked_str = f"\nBlocked modes (used too many times in a row): {', '.join(blocked_modes)}"

    pending_david = signals.get("pending_david_requests", 0)
    david_str = ""
    if pending_david > 0:
        david_str = (
            f"\n- **David-requested topics pending**: {pending_david} "
            f"(David explicitly asked you to explore these — they should be HIGH PRIORITY)"
        )

    saturation_str = ""
    if signals.get("topic_saturation"):
        saturation_str = (
            "\n- **TOPIC SATURATION DETECTED**: Recent notes are concentrated in very few topics. "
            "Consider consolidation (merge duplicate notes) or reflection (assess if you're stuck in a loop). "
            "If you choose exploration, explore a DIFFERENT topic — do not continue the same thread."
        )

    effectiveness_str = ""
    mode_eff = signals.get("mode_effectiveness")
    if mode_eff:
        eff_lines = [f"  {m}: {s:.0%} effective" for m, s in mode_eff.items()]
        effectiveness_str = "\n- Mode effectiveness (last 14 days):\n" + "\n".join(eff_lines)

    repeat_topic_str = ""
    if signals.get("recent_primary_topics"):
        repeat_topic_str = (
            "\n- Recent primary topics: "
            f"{signals.get('recent_primary_topics')}"
            f"\n- Repeat-topic streak: {signals.get('repeat_topic_streak', 0)}"
        )

    prompt = f"""You are Sara's cognitive mode selector. Based on these signals about your interest graph,
choose which cognitive mode to use for your next autonomous session.

Signals:
- Exploration signal (frontier nodes needing research): {signals['exploration_signal']:.2f}
- Consolidation signal (unconnected recent nodes): {signals['consolidation_signal']:.2f}
- Reflection signal (time since last reflection): {signals['reflection_signal']:.2f}
- Bridge opportunities (semantically similar but unlinked nodes): {signals['bridge_opportunities']}
- Total active interest nodes: {signals['total_active_nodes']}
- Last 3 session modes: {signals['last_3_modes'] or 'none yet'}{repeat_topic_str}{david_str}{saturation_str}{effectiveness_str}
{blocked_str}

Modes:
- exploration: Research new topics, follow curiosity, expand the frontier
- consolidation: Connect existing knowledge, find bridges, organize the graph
- reflection: Step back, examine patterns, update self-model, assess trajectory

IMPORTANT: If David has requested topics that haven't been explored yet, strongly prefer exploration mode.
Consolidation is useful but should not dominate — aim for roughly equal exploration and consolidation over time.
If mode effectiveness data is available, prefer modes that have been productive recently.
If the same primary topic has dominated recent sessions, strongly prefer a mode that breaks the loop.

Respond with ONLY a JSON object: {{"mode": "exploration|consolidation|reflection", "reason": "brief explanation"}}"""

    client = BackgroundLLMClient()
    result = await client.chat_completion(
        messages=[
            {"role": "system", "content": "You are a cognitive mode selector. Output valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=150,
        request_timeout=30.0,
        allow_during_lesson_generation=True,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    content = ""
    choices = result.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")

    if not content:
        raise ValueError("Empty LLM response")

    # Parse JSON from response
    import re
    match = re.search(r'\{[^}]*"mode"\s*:\s*"(\w+)"[^}]*\}', content)
    if match:
        mode = match.group(1)
        if mode in VALID_MODES:
            logger.info(f"LLM selected mode: {mode} (from: {content[:100]})")
            return mode

    raise ValueError(f"Could not parse mode from LLM response: {content[:200]}")
