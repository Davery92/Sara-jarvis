"""
Soul Loader — cached loader for Sara's soul content.

Queries the sara_soul table and formats identity/principles/boundaries/growth
into a prompt block. Caches for 5 minutes to avoid per-request DB hits.
"""

import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Cache ──
_soul_cache: Optional[str] = None
_soul_cache_time: float = 0.0
_SOUL_CACHE_TTL = 300  # 5 minutes


def load_soul_for_prompt(db: Session) -> Optional[str]:
    """
    Load Sara's soul sections from DB and format for system prompt injection.

    Returns formatted string on success, None on failure (caller should fall back).
    Cached for 5 minutes.
    """
    global _soul_cache, _soul_cache_time

    now = time.time()
    if _soul_cache is not None and (now - _soul_cache_time) < _SOUL_CACHE_TTL:
        return _soul_cache

    try:
        from app.models.soul import SaraSoul

        rows = db.query(SaraSoul).filter(
            SaraSoul.section.in_(["identity", "principles", "boundaries", "growth"])
        ).all()

        if not rows:
            logger.warning("sara_soul table is empty — falling back to hardcoded personality")
            _soul_cache = None
            _soul_cache_time = now
            return None

        sections = {row.section: row.content for row in rows}

        # identity is required; others are optional
        if "identity" not in sections:
            logger.warning("sara_soul missing 'identity' section — falling back")
            _soul_cache = None
            _soul_cache_time = now
            return None

        parts = [f"## Who Sara Is\n\n{sections['identity']}"]

        operational = []
        if "principles" in sections:
            operational.append(f"### Principles\n{sections['principles']}")
        if "boundaries" in sections:
            operational.append(f"### Boundaries\n{sections['boundaries']}")
        if "growth" in sections:
            operational.append(f"### Current Growth Areas\n{sections['growth']}")

        if operational:
            parts.append("---\n\n## How Sara Operates\n\n" + "\n\n".join(operational))

        result = "\n\n".join(parts)
        _soul_cache = result
        _soul_cache_time = now
        logger.info("Soul loaded from DB (%d sections, %d chars)", len(sections), len(result))
        return result

    except Exception as e:
        logger.error("Failed to load soul from DB: %s", e)
        return None


def invalidate_soul_cache() -> None:
    """Clear the soul cache — call when a soul proposal is approved."""
    global _soul_cache, _soul_cache_time
    _soul_cache = None
    _soul_cache_time = 0.0
