"""
Unified Heartbeat Agent — DEPRECATED

Replaced by unified_agent.py which consolidates both this module
(heartbeat/THINK) and subconscious_service.py (sensing) into a single
4-phase cycle. The Celery beat schedule now points to
app.tasks.autonomy.unified_agent.

This stub re-exports run_unified_agent for backward compatibility.
"""

import logging

logger = logging.getLogger(__name__)

_warned = False


async def run_unified_heartbeat(db, user_id: str = "64f37c56-85cb-4590-8de9-adfc17d343ed"):
    """
    DEPRECATED: Use run_unified_agent from services.unified_agent instead.
    Warns on first invocation only, then delegates silently.
    """
    global _warned
    if not _warned:
        logger.warning(
            "unified_heartbeat.run_unified_heartbeat() is deprecated — "
            "use services.unified_agent.run_unified_agent() directly"
        )
        _warned = True

    from app.services.unified_agent import run_unified_agent
    return await run_unified_agent(db, user_id)
