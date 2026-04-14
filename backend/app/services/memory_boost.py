"""
Memory Boost Service — boosts episode scores when they're recalled and referenced.

Two signals:
1. Access boost: Every time an episode is recalled (via memory search), increment access_count
2. Reference boost: When Sara's response references recalled content, boost rating_boost

These feed into the nightly importance rescoring cycle.
"""

import logging
from typing import List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def boost_referenced_memories(
    user_id: str,
    recalled_episode_ids: List[str],
    response_text: str,
    recalled_contents: Optional[List[str]] = None,
):
    """
    Boost rating_boost for episodes whose content appears in Sara's response.

    Args:
        user_id: User ID
        recalled_episode_ids: IDs of episodes that were recalled for context
        response_text: Sara's response text
        recalled_contents: Content snippets of recalled episodes (for matching)
    """
    if not recalled_episode_ids or not response_text:
        return

    from app.db.session import get_async_session_factory

    response_lower = response_text.lower()
    boost_ids = []

    if recalled_contents:
        # Check which recalled memories were actually referenced in the response
        for eid, content in zip(recalled_episode_ids, recalled_contents):
            if not content:
                continue
            # Extract key phrases (words > 5 chars) from the recalled content
            words = [w for w in content.lower().split() if len(w) > 5]
            if not words:
                continue
            # If 30%+ of key words appear in Sara's response, it was referenced
            matches = sum(1 for w in words[:20] if w in response_lower)
            if matches >= max(2, len(words[:20]) * 0.3):
                boost_ids.append(eid)
    else:
        # No content to match — boost all recalled episodes slightly
        boost_ids = recalled_episode_ids

    if not boost_ids:
        return

    try:
        async_session = get_async_session_factory()
        async with async_session() as db:
            await db.execute(text("""
                UPDATE episode
                SET rating_boost = LEAST(1.0, COALESCE(rating_boost, 0) + 0.05),
                    access_count = COALESCE(access_count, 0) + 1,
                    last_accessed = NOW()
                WHERE id = ANY(:ids) AND user_id = :uid
            """), {"ids": boost_ids, "uid": user_id})
            await db.commit()
            logger.info(f"Boosted {len(boost_ids)} referenced memories for user {user_id[:8]}")
    except Exception as e:
        logger.debug(f"Memory boost failed: {e}")
