"""
ACS Context Assembler — builds the self-context packet for autonomous sessions.

Reuses existing services: soul_loader, stable/day layers, memory, working memory.

v2 adds assemble_context_v2() with async support, interest graph context,
self-model context, and mode-specific context blocks.
"""

import json
import logging
import os
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
HANDOFF_KEY = "sara:acs:last_handoff:{user_id}"
OPEN_THREADS_KEY = "sara:acs:open_threads:{user_id}"
DAILY_PLAN_KEY = "sara:acs:daily_plan:{user_id}"


# ── Async Context Assembly ──

async def assemble_context_v2(user_id: str, mode: str) -> dict:
    """Assemble the full context packet for a v2 autonomous session (async).

    Runs block builders in parallel. Critical blocks (soul, self_model,
    mode_context) fail loud — if any raise, the exception propagates so the
    caller (session start) fails rather than silently producing a degraded
    prompt. Secondary blocks (interest graph, journals, PKG, calendar, etc.)
    degrade gracefully with a visible marker in the rendered prompt so the
    LLM knows context is missing.
    """
    import asyncio

    # (name, coroutine, is_critical)
    # Order determines key mapping below — do not reorder without updating
    # both the gather() and the return dict.
    builders = [
        ("soul_block",            _async_load_soul(user_id),                      True),
        ("context_block",         _async_build_context_block(user_id),            False),
        ("interest_graph_block",  _build_interest_graph_block(user_id),           False),
        ("self_model_block",      _build_self_model_block(user_id),               True),
        ("mode_context_block",    _build_mode_context_block(user_id, mode),       True),
        ("show_david_block",      _async_build_show_david_block(user_id),         False),
        ("handoff_block",         _async_load_session_history(user_id),           False),
        ("temporal_block",        _build_temporal_block(user_id),                 False),
        ("journal_context_block", _build_journal_context(user_id),                False),
        ("open_threads_block",    _async_load_open_threads(user_id),              False),
        ("daily_plan_block",      _async_load_daily_plan(user_id),                False),
        ("pkg_context_block",     _build_pkg_context_block(user_id),              False),
        ("calendar_context_block", _build_calendar_context_block(user_id),        False),
        ("operational_knowledge_block", _build_operational_knowledge_block(user_id), False),
        ("directives_block",      _async_load_directives(user_id),                False),
    ]
    results = await asyncio.gather(
        *(b[1] for b in builders),
        return_exceptions=True,
    )

    out: dict = {}
    for (name, _coro, critical), val in zip(builders, results):
        if isinstance(val, BaseException):
            if critical:
                logger.error(
                    f"ACS context assembly: critical block '{name}' failed: {val}",
                    exc_info=val,
                )
                raise val
            logger.warning(f"ACS context assembly: block '{name}' failed, degrading: {val}")
            out[name] = f"*[{name} unavailable: {type(val).__name__}]*"
        else:
            out[name] = val if isinstance(val, str) else ""

    # Prepend daily plan to handoff block so Sara sees her plan for the day
    daily_plan = out.pop("daily_plan_block", "")
    if daily_plan:
        out["handoff_block"] = f"## Today's Plan\n{daily_plan}\n\n{out.get('handoff_block', '')}".strip()

    return out


async def _async_load_soul(user_id: str) -> str:
    """
    Load soul context — concatenates all sections of the sara_soul table.

    The sara_soul table is a section-keyed identity document (identity,
    principles, boundaries, growth, evolution_log). The previous version of
    this function queried `WHERE active = TRUE` against a column that does
    not exist on the table, which silently failed and returned an empty
    string — leaving "(Soul context not available)" in every system prompt.
    """
    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT section, content FROM sara_soul
                ORDER BY
                    CASE section
                        WHEN 'identity'      THEN 0
                        WHEN 'principles'    THEN 1
                        WHEN 'boundaries'    THEN 2
                        WHEN 'growth'        THEN 3
                        WHEN 'evolution_log' THEN 4
                        ELSE 9
                    END
            """))
            rows = result.fetchall()
            if not rows:
                return ""
            parts = ["## Who You Are (Soul)"]
            for section, content in rows:
                if not content:
                    continue
                # Pretty-print the section header in title case
                heading = section.replace("_", " ").title()
                parts.append(f"### {heading}")
                parts.append(content.strip())
            return "\n".join(parts)
    except Exception as e:
        logger.debug(f"Async soul load failed: {e}")
        return ""


async def _async_build_context_block(user_id: str) -> str:
    """Build context from stable/day layers and recent episodes (async)."""
    parts = []
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()

    async with async_session() as db:
        # Recent episodes (last 5)
        try:
            result = await db.execute(text("""
                SELECT content, importance, created_at
                FROM episode
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT 5
            """), {"uid": user_id})
            rows = result.fetchall()
            if rows:
                ep_lines = []
                for row in rows:
                    content = (row[0] or "")[:200]
                    ts = row[2].strftime('%H:%M') if row[2] else '?'
                    ep_lines.append(f"- [{ts}] {content}")
                parts.append("## Recent Memories\n" + "\n".join(ep_lines))
        except Exception as e:
            logger.debug(f"Async episode fetch failed: {e}")

    # Try sync stable/day layers via thread pool
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        from app.db.base import SessionLocal
        db = SessionLocal()
        try:
            from app.services.daily_brief.stable_layer import build_stable_layer
            stable = build_stable_layer(db, user_id)
            if stable:
                parts.insert(0, f"## World Context\n{stable}")
        except Exception:
            pass
        try:
            from app.services.daily_brief.day_layer import build_day_layer
            day = build_day_layer(db, user_id)
            if day:
                parts.insert(min(1, len(parts)), f"## Today\n{day}")
        except Exception:
            pass
        db.close()
    except Exception:
        pass

    return "\n\n".join(parts) if parts else ""


async def _build_interest_graph_block(user_id: str) -> str:
    """Build interest graph context block."""
    try:
        from app.services.acs.interest_graph import InterestGraph
        graph = InterestGraph()

        # Periodically sync PKG interests into interest graph (24h cooldown)
        try:
            await graph.sync_from_pkg(user_id)
        except Exception as e:
            logger.debug(f"PKG sync during context build failed: {e}")

        data = await graph.get_graph_for_context(user_id)

        if not data["nodes"]:
            return "(Interest graph is empty — explore freely!)"

        lines = [f"Active: {data['stats']['total_active']} nodes, showing top {len(data['nodes'])}"]
        for node in data["nodes"]:
            fasc = node.get("fascination", 0)
            depth = node.get("depth", 0)
            tag = " [David requested]" if node.get("source") == "david_request" else ""
            lines.append(
                f"- {node['label']}{tag} (f={fasc:.1f}, d={depth:.1f})"
            )
        # Skip edges to save context budget
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"Interest graph block build failed: {e}")
        return ""


async def _build_self_model_block(user_id: str) -> str:
    """Build self-model context block."""
    try:
        from app.services.acs.self_model import SelfModel
        sm = SelfModel()
        return await sm.get_for_context(user_id)
    except Exception as e:
        logger.debug(f"Self-model block build failed: {e}")
        return ""


async def _build_mode_context_block(user_id: str, mode: str) -> str:
    """Build mode-specific context block."""
    try:
        from app.services.acs.interest_graph import InterestGraph
        graph = InterestGraph()

        if mode == "exploration":
            return await _exploration_context(user_id, graph)
        elif mode == "consolidation":
            return await _consolidation_context(user_id, graph)
        elif mode == "reflection":
            return await _reflection_context(user_id)
        return ""
    except Exception as e:
        logger.debug(f"Mode context block build failed: {e}")
        return ""


async def _get_david_requested_nodes(user_id: str) -> list:
    """Fetch active interest nodes that David explicitly asked Sara to explore."""
    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT id, label, description, fascination, depth, source_detail
                FROM acs_interest_node
                WHERE user_id = :uid
                  AND source = 'david_request'
                  AND status = 'active'
                  AND depth < 0.6
                ORDER BY fascination DESC, created_at DESC
                LIMIT 5
            """), {"uid": user_id})
            return [
                {
                    "id": r[0], "label": r[1], "description": r[2],
                    "fascination": float(r[3]), "depth": float(r[4]),
                    "source_detail": r[5],
                }
                for r in result.fetchall()
            ]
    except Exception as e:
        logger.debug(f"Failed to fetch david_request nodes: {e}")
        return []


async def _exploration_context(user_id: str, graph) -> str:
    """Context specific to exploration mode."""
    parts = ["## Exploration Context"]

    # David-requested topics (highest priority)
    david_requested = await _get_david_requested_nodes(user_id)
    if david_requested:
        parts.append("**David asked you to explore:**")
        for n in david_requested:
            parts.append(
                f"- **{n['label']}** (depth={n['depth']:.2f}): "
                f"{(n.get('source_detail') or n.get('description') or '')[:120]}"
            )

    # Frontier nodes
    frontier = await graph.get_frontier_nodes(user_id, limit=5)
    if frontier:
        parts.append("**Frontier (high fascination, low depth):**")
        for n in frontier:
            parts.append(f"- {n['label']} (fascination={n['fascination']:.2f}, depth={n['depth']:.2f})")

    # Bridge opportunities
    bridges = await graph.find_bridge_opportunities(user_id, limit=3)
    if bridges:
        parts.append("**Bridge opportunities (semantically similar, unlinked):**")
        for b in bridges:
            parts.append(
                f"- {b['node_a']['label']} ↔ {b['node_b']['label']} "
                f"(similarity={b['similarity']:.2f})"
            )

    # Handoff intent from last session
    handoff = _load_last_handoff(user_id)
    if handoff:
        parts.append(handoff)

    return "\n".join(parts) if len(parts) > 1 else ""


async def _consolidation_context(user_id: str, graph) -> str:
    """Context specific to consolidation mode."""
    parts = ["## Consolidation Context"]

    # Disconnected clusters
    clusters = await graph.get_disconnected_clusters(user_id)
    if len(clusters) > 1:
        parts.append(f"**Disconnected clusters: {len(clusters)}**")
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            for i, cluster in enumerate(clusters[:5]):
                result = await db.execute(text("""
                    SELECT label FROM acs_interest_node WHERE id = ANY(:ids)
                """), {"ids": cluster[:3]})
                labels = [r[0] for r in result.fetchall()]
                parts.append(f"  Cluster {i + 1}: {', '.join(labels)}{'...' if len(cluster) > 3 else ''}")

    # Recent unlinked nodes
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT n.label, n.fascination FROM acs_interest_node n
            WHERE n.user_id = :uid AND n.status = 'active'
              AND n.created_at > NOW() - INTERVAL '72 hours'
              AND NOT EXISTS (
                  SELECT 1 FROM acs_interest_edge e
                  WHERE e.source_node_id = n.id OR e.target_node_id = n.id
              )
            ORDER BY n.fascination DESC LIMIT 5
        """), {"uid": user_id})
        unlinked = result.fetchall()
        if unlinked:
            parts.append("**Recent unlinked nodes:**")
            for r in unlinked:
                parts.append(f"- {r[0]} (fascination={r[1]:.2f})")

    return "\n".join(parts) if len(parts) > 1 else ""


async def _reflection_context(user_id: str) -> str:
    """Context specific to reflection mode."""
    parts = ["## Reflection Context"]

    # Self-model version history
    from app.services.acs.self_model import SelfModel
    sm = SelfModel()
    history = await sm.get_version_history(user_id, limit=5)
    if history:
        parts.append(f"**Self-model versions: {len(history)} (showing latest)**")
        for h in history[:3]:
            parts.append(f"  v{h['version']} ({h['created_at'][:10] if h['created_at'] else '?'})")

    # Session mode distribution
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT mode, COUNT(*) FROM acs_session_log
            WHERE user_id = :uid AND mode IS NOT NULL
            GROUP BY mode
        """), {"uid": user_id})
        mode_dist = {r[0]: r[1] for r in result.fetchall()}
        if mode_dist:
            parts.append("**Session mode distribution:** " + ", ".join(
                f"{k}: {v}" for k, v in mode_dist.items()
            ))

        # Interest graph trends
        result = await db.execute(text("""
            SELECT COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') AS recent,
                   COUNT(*) FILTER (WHERE status = 'dormant') AS dormant,
                   COUNT(*) FILTER (WHERE status = 'active') AS active
            FROM acs_interest_node
            WHERE user_id = :uid
        """), {"uid": user_id})
        row = result.fetchone()
        if row:
            parts.append(
                f"**Graph trends:** {row[2]} active nodes, "
                f"{row[0]} added in last 7 days, {row[1]} dormant"
            )

    return "\n".join(parts) if len(parts) > 1 else ""


async def _build_temporal_block(user_id: str) -> str:
    """Build temporal grounding so Sara knows the current date and how long ACS has been running."""
    try:
        from datetime import datetime, timezone
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()

        now = datetime.now(timezone.utc)
        parts = [f"## Temporal Grounding", f"Current date: {now.strftime('%Y-%m-%d %H:%M UTC')}"]

        async with async_session() as db:
            # When ACS first started
            result = await db.execute(text("""
                SELECT MIN(started_at), COUNT(*),
                       COUNT(*) FILTER (WHERE mode = 'exploration'),
                       COUNT(*) FILTER (WHERE mode = 'consolidation'),
                       COUNT(*) FILTER (WHERE mode = 'reflection')
                FROM acs_session
                WHERE user_id = :uid
            """), {"uid": user_id})
            row = result.fetchone()
            if row and row[0]:
                first_session = row[0]
                if first_session.tzinfo is None:
                    first_session = first_session.replace(tzinfo=timezone.utc)
                days_running = (now - first_session).days
                parts.append(
                    f"Your autonomous cognition system started on {first_session.strftime('%Y-%m-%d')} "
                    f"({days_running} days ago). You have run {row[1]} sessions total "
                    f"(exploration: {row[2]}, consolidation: {row[3]}, reflection: {row[4]})."
                )
                if row[3] > row[2] * 1.5:
                    parts.append(
                        "Note: You have been running significantly more consolidation than exploration. "
                        "Consider spending more time exploring new topics, especially any David has requested."
                    )

        return "\n".join(parts)
    except Exception as e:
        logger.debug(f"Temporal block build failed: {e}")
        from datetime import datetime, timezone
        return f"## Temporal Grounding\nCurrent date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"


async def _build_journal_context(user_id: str) -> str:
    """Fetch today's journal entries so Sara avoids repeating observations."""
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from app.db.session import get_async_session_factory

        est = ZoneInfo("America/New_York")
        today = datetime.now(est).strftime("%Y-%m-%d")
        journal_title = f"Sara's Journal — {today}"

        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT content FROM note
                WHERE user_id = :uid AND title = :title
                ORDER BY updated_at DESC
                LIMIT 1
            """), {"uid": user_id, "title": journal_title})
            row = result.fetchone()
            if row and row[0]:
                content = row[0]
                # Truncate to last ~1500 chars to save context
                if len(content) > 1500:
                    content = "...\n" + content[-1500:]
                return f"## Today's Journal Entries (DO NOT repeat these observations)\n{content}"
        return ""
    except Exception as e:
        logger.debug(f"Journal context build failed: {e}")
        return ""


async def _async_build_show_david_block(user_id: str) -> str:
    """Load unshown show-david items (async)."""
    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT title, category, created_at
                FROM acs_show_david_buffer
                WHERE user_id = :uid AND shown = FALSE
                ORDER BY priority DESC
                LIMIT 5
            """), {"uid": user_id})
            rows = result.fetchall()
            if not rows:
                return ""
            lines = [f"- [{r[1]}] {r[0]}" for r in rows]
            return "Already queued to show David:\n" + "\n".join(lines)
    except Exception as e:
        logger.debug(f"Async show-david fetch failed: {e}")
        return ""


async def _async_load_last_handoff(user_id: str) -> str:
    """Load last session handoff from Redis (async) with enriched recap."""
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            raw = await r.get(HANDOFF_KEY.format(user_id=user_id))
            if not raw:
                return ""
            handoff = json.loads(raw)

            # Build enriched recap header
            mode = handoff.get("mode", "unknown")
            turns = handoff.get("turns", "?")
            compactions = handoff.get("compaction_count", 0)
            header = f"## Previous Session Recap\nLast session: {mode} mode, {turns} turns"
            if compactions:
                header += f", {compactions} compaction(s)"

            parts = [header]

            if handoff.get("was_doing"):
                parts.append(f"I was working on: {handoff['was_doing']}")
            if handoff.get("got_to"):
                parts.append(f"I got to: {handoff['got_to']}")

            # Enriched accomplishments
            accomplished = []
            if handoff.get("notes_created"):
                notes = handoff["notes_created"]
                accomplished.append(f"Notes: {', '.join(notes[:5])}")
            if handoff.get("notes_revised"):
                revised = handoff["notes_revised"]
                accomplished.append(f"Revised: {', '.join(revised[:3])}")
            if handoff.get("nodes_created"):
                nodes = handoff["nodes_created"]
                accomplished.append(f"Interest nodes: {', '.join(nodes[:5])}")
            if handoff.get("edges_created") and handoff["edges_created"] > 0:
                accomplished.append(f"Edges: {handoff['edges_created']}")
            if handoff.get("files_touched"):
                files = handoff["files_touched"][:5]
                accomplished.append(f"Files: {', '.join(f'`{f}`' for f in files)}")
            if accomplished:
                parts.append(f"\n**Accomplished:** {'; '.join(accomplished)}")

            if handoff.get("key_findings"):
                findings = handoff["key_findings"][:3]
                parts.append(f"**Key findings:** {'; '.join(findings)}")

            if handoff.get("next_time"):
                parts.append(f"**Next time:** {handoff['next_time']}")
            if handoff.get("open_questions"):
                parts.append(f"**Open questions:** {handoff['open_questions']}")

            if handoff.get("files_touched"):
                files = handoff["files_touched"]
                parts.append(
                    "\n**Files from last session** (use read_file on these directly — "
                    "do NOT search from scratch):"
                )
                for f in files[:10]:
                    parts.append(f"  - `{f}`")

            return "\n".join(parts)
        finally:
            if hasattr(r, 'aclose'):
                await r.aclose()
            else:
                await r.close()
    except Exception as e:
        logger.debug(f"Async handoff load failed: {e}")
        return ""


async def _async_load_open_threads(user_id: str) -> str:
    """Load active open threads from Redis for context injection."""
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            raw_threads = await r.hgetall(OPEN_THREADS_KEY.format(user_id=user_id))
            if not raw_threads:
                return ""

            active = []
            for raw in raw_threads.values():
                try:
                    t = json.loads(raw)
                    if t.get("status") == "active":
                        active.append(t)
                except (json.JSONDecodeError, KeyError):
                    continue

            if not active:
                return ""

            # Sort by priority then recency
            priority_order = {"high": 0, "medium": 1, "low": 2}
            active.sort(key=lambda t: (priority_order.get(t.get("priority", "medium"), 1), t.get("updated_at", "")))

            parts = ["## Open Research Threads",
                     "These are threads you're actively pursuing across sessions. "
                     "Use update_thread to record progress, resolve_thread when done.",
                     ""]
            for t in active:
                parts.append(f"### [{t.get('priority', 'medium').upper()}] {t['title']} (id: {t['id']})")
                parts.append(f"{t.get('description', '')}")
                # Show latest progress entry if any
                progress = t.get("progress", [])
                if progress:
                    latest = progress[-1]
                    parts.append(f"Latest progress: {latest.get('text', '')}")
                    if latest.get("next_steps"):
                        parts.append(f"Next steps: {latest['next_steps']}")
                if t.get("next_steps"):
                    parts.append(f"Next steps: {t['next_steps']}")
                parts.append("")

            return "\n".join(parts)
        finally:
            if hasattr(r, 'aclose'):
                await r.aclose()
            else:
                await r.close()
    except Exception as e:
        logger.debug(f"Async open threads load failed: {e}")
        return ""


async def _async_load_daily_plan(user_id: str) -> str:
    """Load today's plan context — structured items with status + prose plan."""
    from datetime import date

    parts = []
    have_structured_items = False

    # Load structured plan items from database
    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT title, status, priority, source, result_summary, blocker_reason
                FROM acs_plan_item
                WHERE user_id = :uid AND plan_date = :today
                ORDER BY
                    CASE WHEN source = 'david_chat' THEN 0 ELSE 1 END,
                    priority DESC
            """), {"uid": user_id, "today": date.today()})
            items = result.fetchall()

            if items:
                have_structured_items = True
                status_icons = {
                    "completed": "DONE", "in_progress": "NOW",
                    "pending": "TODO", "blocked": "BLOCKED",
                    "deferred": "LATER", "cancelled": "SKIP",
                }
                lines = []
                for item in items:
                    icon = status_icons.get(item[1], item[1].upper())
                    source_tag = " [from David]" if item[3] == "david_chat" else ""
                    line = f"- [{icon}] {item[0]}{source_tag}"
                    if item[1] == "completed" and item[4]:
                        line += f" — {item[4][:100]}"
                    elif item[1] == "blocked" and item[5]:
                        line += f" — Blocked: {item[5][:100]}"
                    lines.append(line)

                done = sum(1 for i in items if i[1] == "completed")
                total = len(items)
                parts.append(f"### Plan Items ({done}/{total} complete)")
                parts.extend(lines)
    except Exception as e:
        logger.debug(f"Plan items load failed: {e}")

    # Only fall back to the prose Redis plan when no structured items exist.
    # The Redis note often lags behind completed work and can contradict the
    # current plan-item state, which confuses ACS during prompt assembly.
    if not have_structured_items:
        try:
            import redis.asyncio as aioredis
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            try:
                plan = await r.get(DAILY_PLAN_KEY.format(user_id=user_id))
                if plan:
                    parts.append("\n### Plan Notes")
                    parts.append(plan)
            finally:
                if hasattr(r, 'aclose'):
                    await r.aclose()
                else:
                    await r.close()
        except Exception as e:
            logger.debug(f"Async daily plan load failed: {e}")

    return "\n".join(parts) if parts else ""


async def build_audit_context_block(session_id: str, current_turn: int = 0) -> str:
    """
    Render the most recent audit dialogue + resolution as a context block
    that gets prepended to Sara's turn prompt right after she resumes from
    an audit. This is how Sara "remembers" the conversation she just had
    with the auditor.

    Returns "" if there is no recent audit for this session, or if the
    audit is stale (more than AUDIT_CONTEXT_EXPIRY_TURNS turns ago).
    """
    if not session_id:
        return ""
    try:
        from app.services.acs.auditor import get_recent_audit_for_session, AUDIT_CONTEXT_EXPIRY_TURNS
        audit = await get_recent_audit_for_session(session_id)
        if not audit:
            return ""

        # Check staleness: if we know the current turn and the audit was
        # recorded with a turn number, skip if it's too old. We also check
        # the timestamp — if the audit is more than 15 minutes old, it's stale.
        resolved_at = audit.get("resolved_at")
        if resolved_at:
            from datetime import datetime, timezone
            try:
                if isinstance(resolved_at, str):
                    from dateutil.parser import parse as parse_dt
                    resolved_dt = parse_dt(resolved_at)
                else:
                    resolved_dt = resolved_at
                if resolved_dt.tzinfo is None:
                    resolved_dt = resolved_dt.replace(tzinfo=timezone.utc)
                age_minutes = (datetime.now(timezone.utc) - resolved_dt).total_seconds() / 60
                if age_minutes > 15:
                    return ""
            except Exception:
                pass

        messages = audit.get("messages") or []
        if not messages:
            return ""
        lines = [
            "## Recent Auditor Intervention",
            f"_(triggered by {audit.get('trigger_kind')}: "
            f"{(audit.get('trigger_reason') or '')[:200]})_",
            "",
            "### Dialogue",
        ]
        for m in messages:
            role = "AUDITOR" if m.get("role") == "auditor" else "YOU (SARA)"
            content = (m.get("content") or "").strip()
            lines.append(f"**{role}:** {content}")
            lines.append("")
        outcome = audit.get("outcome") or "unknown"
        resolution = audit.get("resolution") or ""
        lines.append(f"### Resolution ({outcome})")
        lines.append(resolution)
        lines.append("")
        lines.append(
            "_The auditor has set the direction above. Take it seriously — "
            "they had outside perspective on patterns you may not have noticed. "
            "Adjust your next turn accordingly._"
        )
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"Audit context block failed for session {session_id[:8]}: {e}")
        return ""


async def _build_pkg_context_block(user_id: str) -> str:
    """Build PKG context block so Sara knows about David's life during autonomous sessions."""
    try:
        from app.services.pkg_context_provider import pkg_context
        from app.services.personal_knowledge_graph import personal_kg

        # Pull a few extra facts so the post-filter still has enough to render.
        summary = personal_kg.get_david_summary(max_facts=25)
        if not summary:
            return ""

        # Filter out gym/workout routines — they bloat the prompt with
        # information that isn't useful for autonomous reasoning, and David
        # doesn't want Sara meditating on his split routine.
        filtered_lines = []
        for line in summary.split("\n"):
            low = line.lower()
            if "🏋️" in line:
                continue
            if any(tag in low for tag in (
                "push a", "push b", "pull a", "pull b", "legs a", "legs b",
            )):
                continue
            filtered_lines.append(line)
        summary = "\n".join(filtered_lines).strip()
        if not summary:
            return ""

        if len(summary) > 1000:
            summary = summary[:1000] + "\n[truncated]"

        return f"## What You Know About David\n{summary}"
    except Exception as e:
        logger.debug(f"PKG context block build failed: {e}")
        return ""


async def _build_calendar_context_block(user_id: str) -> str:
    """Build calendar context with semantic annotations for ACS sessions."""
    try:
        from app.services.calendar_intelligence import get_annotated_schedule
        schedule = await get_annotated_schedule(user_id, days_ahead=7)
        if not schedule:
            return ""
        return f"## David's Upcoming Schedule\n{schedule}"
    except Exception as e:
        logger.debug(f"Calendar context block build failed: {e}")
        return ""


OPERATIONAL_KNOWLEDGE_FOLDER = "Sara Operational"


async def _build_operational_knowledge_block(user_id: str) -> str:
    """Load notes from the 'Sara Operational' folder as ground-truth reference.

    These are persistent facts about Sara's capabilities, environment, and
    resources that she should always trust over her own assumptions.
    David maintains these notes to correct recurring misconceptions.
    """
    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()

        async with async_session() as db:
            # Find the operational knowledge folder
            result = await db.execute(text("""
                SELECT id FROM folder
                WHERE user_id = :uid AND name = :folder_name
                LIMIT 1
            """), {"uid": user_id, "folder_name": OPERATIONAL_KNOWLEDGE_FOLDER})
            folder_row = result.fetchone()
            if not folder_row:
                return ""

            folder_id = folder_row[0]

            # Load all notes in that folder
            result = await db.execute(text("""
                SELECT title, content FROM note
                WHERE user_id = :uid AND folder_id = :fid
                ORDER BY updated_at DESC
                LIMIT 5
            """), {"uid": user_id, "fid": folder_id})
            rows = result.fetchall()
            if not rows:
                return ""

            parts = [
                "## Operational Knowledge (GROUND TRUTH)",
                "The following are verified facts about your capabilities, environment, and resources.",
                "These are maintained by David and are ALWAYS accurate. If you believe something",
                "contradicts this section, trust this section — your assumption is wrong.",
                "",
            ]
            for title, content in rows:
                parts.append(f"### {title}")
                # Cap each note at 1000 chars to stay within context budget
                if content and len(content) > 1000:
                    parts.append(content[:1000] + "\n[truncated]")
                else:
                    parts.append(content or "(empty)")
                parts.append("")

            return "\n".join(parts)
    except Exception as e:
        logger.debug(f"Operational knowledge block build failed: {e}")
        return ""


# ── Session History (replaces single-handoff loading) ──

async def _async_load_session_history(user_id: str) -> str:
    """Load last 5 session summaries + enriched most-recent handoff.

    Replaces the old _async_load_last_handoff with richer multi-session context
    so Sara knows where she's been, not just her last session.
    """
    try:
        from app.db.session import get_async_session_factory
        import redis.asyncio as aioredis

        parts = ["## Session History"]
        async_session = get_async_session_factory()

        # 1. Load last 5 session summaries from DB
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT sl.session_id, sl.mode, sl.summary, sl.avg_engagement,
                       sl.notes_written, sl.nodes_created, sl.edges_created,
                       sl.next_session_intent, sl.duration_minutes,
                       s.started_at, s.ended_at, s.end_reason, s.turns_completed
                FROM acs_session_log sl
                JOIN acs_session s ON s.id = sl.session_id
                WHERE sl.user_id = :uid
                ORDER BY s.started_at DESC
                LIMIT 5
            """), {"uid": user_id})
            sessions = result.fetchall()

            if not sessions:
                # Fall back to basic session query without session_log
                result = await db.execute(text("""
                    SELECT id, cognitive_mode, turns_completed, notes_created,
                           started_at, ended_at, end_reason
                    FROM acs_session
                    WHERE user_id = :uid AND state = 'ended'
                    ORDER BY started_at DESC
                    LIMIT 5
                """), {"uid": user_id})
                basic_sessions = result.fetchall()
                if basic_sessions:
                    for i, s in enumerate(basic_sessions):
                        ts = s[4].strftime('%m/%d %H:%M') if s[4] else '?'
                        mode = s[1] or 'unknown'
                        parts.append(
                            f"- [{ts}] {mode} mode, {s[2]} turns, {s[3]} notes"
                            f" — ended: {s[6] or '?'}"
                        )
                else:
                    parts.append("No previous sessions found — this is a fresh start.")
                return "\n".join(parts)

            # Format sessions: most recent gets full detail, rest get summaries
            for i, s in enumerate(sessions):
                sid = s[0][:8] if s[0] else '?'
                mode = s[1] or 'unknown'
                started = s[9].strftime('%m/%d %H:%M') if s[9] else '?'
                duration = f"{s[8]:.0f}min" if s[8] else '?'
                turns = s[12] or 0

                if i == 0:
                    # Most recent session — full detail
                    parts.append(f"\n### Most Recent Session ({sid}) — {started}")
                    parts.append(f"Mode: {mode} | Duration: {duration} | Turns: {turns}")
                    if s[2]:  # summary
                        parts.append(f"Summary: {s[2][:500]}")
                    stats = []
                    if s[4]:  # notes_written
                        stats.append(f"{s[4]} notes")
                    if s[5]:  # nodes_created
                        stats.append(f"{s[5]} interest nodes")
                    if s[6]:  # edges_created
                        stats.append(f"{s[6]} edges")
                    if stats:
                        parts.append(f"Output: {', '.join(stats)}")
                    if s[7]:  # next_session_intent
                        parts.append(f"Next session intent: {s[7][:300]}")
                    if s[11]:  # end_reason
                        parts.append(f"Ended: {s[11]}")
                    # Reference to full log
                    if s[9]:
                        log_date = s[9].strftime('%Y-%m-%d')
                        parts.append(
                            f"Full transcript: see 'ACS Session Log — {log_date}'"
                        )
                else:
                    # Older sessions — compact summary
                    summary_preview = (s[2] or '')[:120]
                    parts.append(
                        f"- [{started}] {mode} mode, {duration}, {turns} turns"
                        f"{f': {summary_preview}' if summary_preview else ''}"
                    )

        # 2. Load enriched handoff from Redis (most recent session details)
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            raw = await r.get(HANDOFF_KEY.format(user_id=user_id))
            if raw:
                handoff = json.loads(raw)
                if handoff.get("was_doing"):
                    parts.append(f"\n**Was doing:** {handoff['was_doing']}")
                if handoff.get("got_to"):
                    parts.append(f"**Got to:** {handoff['got_to']}")
                if handoff.get("next_time"):
                    parts.append(f"**Next time:** {handoff['next_time']}")
                if handoff.get("open_questions"):
                    parts.append(f"**Open questions:** {handoff['open_questions']}")
                if handoff.get("files_touched"):
                    files = handoff["files_touched"][:10]
                    parts.append(
                        "\n**Files from last session** (use read_file directly):"
                    )
                    for f in files:
                        parts.append(f"  - `{f}`")
        finally:
            if hasattr(r, 'aclose'):
                await r.aclose()
            else:
                await r.close()

        return "\n".join(parts)

    except Exception as e:
        logger.debug(f"Session history load failed: {e}")
        # Fall back to old handoff loader
        return await _async_load_last_handoff(user_id)


# ── Directives (David → ACS communication) ──

async def _async_load_directives(user_id: str) -> str:
    """Load pending directives from David for injection into session context."""
    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()

        async with async_session() as db:
            result = await db.execute(text("""
                SELECT id, directive_type, content, priority, created_at
                FROM acs_directive
                WHERE user_id = :uid AND status IN ('pending', 'acknowledged')
                ORDER BY
                    CASE WHEN priority = 'urgent' THEN 0
                         WHEN priority = 'normal' THEN 1
                         ELSE 2 END,
                    created_at DESC
                LIMIT 10
            """), {"uid": user_id})
            rows = result.fetchall()

            if not rows:
                return ""

            type_emoji = {
                "stop": "STOP",
                "focus": "FOCUS",
                "redirect": "REDIRECT",
                "context": "CONTEXT",
                "question": "QUESTION",
            }

            parts = [
                "## David's Directives",
                "These are direct messages from David. READ AND ACKNOWLEDGE each one.",
                "Use the `acknowledge_directive` tool to respond to each directive.",
                "",
            ]
            for r in rows:
                did = r[0][:8]
                dtype = type_emoji.get(r[1], r[1].upper())
                content = r[2]
                priority = r[3]
                ts = r[4].strftime('%m/%d %H:%M') if r[4] else ''
                urgent_tag = " **[URGENT]**" if priority == "urgent" else ""
                parts.append(f"- [{dtype}]{urgent_tag} (id: {r[0]}) {content} ({ts})")

            parts.append("")
            parts.append(
                "STOP directives are non-negotiable — immediately stop the indicated activity. "
                "FOCUS directives are high priority — pivot to the indicated topic. "
                "REDIRECT directives mean change course as described. "
                "CONTEXT directives are informational — absorb and apply. "
                "QUESTION directives need a response via acknowledge_directive."
            )

            return "\n".join(parts)

    except Exception as e:
        logger.debug(f"Directives load failed: {e}")
        return ""


async def load_directives_for_refresh(user_id: str) -> str:
    """Load directives for mid-session context refresh (called from session_manager)."""
    return await _async_load_directives(user_id)
