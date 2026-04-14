"""
ACS Self-Model Service — manages versioned JSONB self-model documents.

The self-model is distinct from the soul: the soul defines who Sara IS,
while the self-model tracks where Sara IS intellectually —
her evolving interests, changed minds, convictions, and self-observations.
"""

import copy
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SELF_MODEL_CACHE_KEY = "sara:acs:self_model_cache:{user_id}"
CACHE_TTL = 3600  # 1 hour

EMPTY_MODEL = {
    "intellectual_interests": [],
    "changed_minds": [],
    "want_to_understand": [],
    "patterns_noticed": [],
    "convictions": [],
    "self_observations": [],
}

# List field caps
FIELD_CAPS = {
    "changed_minds": 8,
    "convictions": 10,
    "want_to_understand": 8,
    "intellectual_interests": 10,
    "patterns_noticed": 8,
    "self_observations": 8,
}


def _deep_merge(base: dict, updates: dict) -> dict:
    """Deep-merge updates into base. Lists are appended (deduped), dicts are recursively merged.

    For 'convictions' and 'changed_minds', new entries supersede old entries
    about the same subject (detected by keyword overlap). This prevents
    contradictory beliefs from accumulating.
    """
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if key in result and isinstance(result[key], list) and isinstance(value, list):
            if key in ("convictions", "changed_minds"):
                # Reconciliation: new entries replace old ones about the same topic
                result[key] = _reconcile_beliefs(result[key], value)
            else:
                # Append new items, avoiding exact duplicates
                existing = set(json.dumps(x) if isinstance(x, dict) else str(x) for x in result[key])
                for item in value:
                    item_key = json.dumps(item) if isinstance(item, dict) else str(item)
                    if item_key not in existing:
                        result[key].append(item)
                        existing.add(item_key)
        elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _reconcile_beliefs(existing: list, new_items: list) -> list:
    """When adding new convictions/changed_minds, remove old entries that
    contradict or are superseded by the new ones.

    Uses keyword overlap to detect when two beliefs are about the same subject.
    The new entry wins, replacing the old one.
    """
    import re

    def _extract_keywords(text: str) -> set:
        """Extract significant words (3+ chars, lowercased) for topic matching."""
        words = re.findall(r'[a-zA-Z0-9_.-]{3,}', str(text).lower())
        # Filter out very common words
        stop = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can',
            'has', 'her', 'was', 'one', 'our', 'this', 'that', 'with', 'from',
            'they', 'have', 'been', 'will', 'would', 'could', 'should', 'about',
            'into', 'than', 'them', 'then', 'when', 'what', 'which', 'their',
            'there', 'these', 'those', 'more', 'some', 'only', 'other', 'also',
            'now', 'just', 'very', 'type', 'model', 'models',
        }
        return {w for w in words if w not in stop}

    def _topic_overlap(a: str, b: str) -> float:
        """Return Jaccard similarity of keyword sets."""
        ka, kb = _extract_keywords(a), _extract_keywords(b)
        if not ka or not kb:
            return 0.0
        return len(ka & kb) / len(ka | kb)

    result = list(existing)

    for new_item in new_items:
        new_str = str(new_item)
        new_key = json.dumps(new_item) if isinstance(new_item, dict) else new_str

        # Check if this exact item already exists
        existing_keys = set(
            json.dumps(x) if isinstance(x, dict) else str(x) for x in result
        )
        if new_key in existing_keys:
            continue

        # Remove old entries that are about the same topic (high keyword overlap)
        kept = []
        for old_item in result:
            old_str = str(old_item)
            overlap = _topic_overlap(old_str, new_str)
            if overlap > 0.35:
                logger.info(
                    f"Self-model reconciliation: replacing '{old_str[:80]}' "
                    f"with '{new_str[:80]}' (overlap={overlap:.2f})"
                )
            else:
                kept.append(old_item)
        result = kept
        result.append(new_item)

    return result


def _apply_caps(model: dict) -> dict:
    """Enforce maximum list lengths, keeping most recent items."""
    for field, cap in FIELD_CAPS.items():
        if field in model and isinstance(model[field], list) and len(model[field]) > cap:
            model[field] = model[field][-cap:]
    return model


class SelfModel:
    """Manages versioned self-model documents in PostgreSQL with Redis cache."""

    async def get_current(self, user_id: str) -> Dict[str, Any]:
        """Get the current self-model with version metadata."""
        # Fall back to DB (always fetch version/created_at from source of truth)
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()

        async with async_session() as db:
            result = await db.execute(text("""
                SELECT content, version, created_at FROM acs_self_model
                WHERE user_id = :uid
                ORDER BY version DESC
                LIMIT 1
            """), {"uid": user_id})
            row = result.fetchone()

            if row:
                content = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                return {
                    "content": content,
                    "version": row[1],
                    "created_at": row[2].isoformat() if row[2] else None,
                }

        return {"content": copy.deepcopy(EMPTY_MODEL), "version": 0, "created_at": None}

    async def update(
        self, user_id: str, updates: Dict[str, Any], session_id: str = None
    ) -> Dict[str, Any]:
        """Deep-merge updates into current model, create new version, invalidate cache.

        Returns the new model.
        """
        current_data = await self.get_current(user_id)
        current = current_data.get("content", current_data)
        new_model = _deep_merge(current, updates)
        new_model = _apply_caps(new_model)

        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()

        async with async_session() as db:
            # Get next version number
            result = await db.execute(text("""
                SELECT COALESCE(MAX(version), 0) + 1
                FROM acs_self_model WHERE user_id = :uid
            """), {"uid": user_id})
            next_version = result.scalar()

            await db.execute(text("""
                INSERT INTO acs_self_model (id, user_id, version, content, session_id, created_at)
                VALUES (:id, :uid, :ver, :content, :sid, NOW())
            """), {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "ver": next_version,
                "content": json.dumps(new_model),
                "sid": session_id,
            })
            await db.commit()

            # Prune old versions, keep only last 20
            if next_version > 20:
                await db.execute(text("""
                    DELETE FROM acs_self_model
                    WHERE user_id = :uid AND version <= :cutoff
                """), {"uid": user_id, "cutoff": next_version - 20})
                await db.commit()

        # Invalidate cache and re-cache
        await self._cache_model(user_id, new_model)

        logger.info(f"Self-model updated to v{next_version} for user {user_id}")
        return new_model

    async def replace(
        self, user_id: str, new_content: Dict[str, Any], session_id: str = None
    ) -> Dict[str, Any]:
        """
        Manually replace the entire self-model with `new_content` and create
        a new version. Unlike `update()`, this performs NO deep-merge and NO
        belief reconciliation — the new content is written exactly as given,
        with only the standard list-length caps applied.

        This is the path used by user-facing edits (the ACS Self-Model UI),
        where the user has reviewed the JSON and wants their version to win
        over whatever Sara had written.

        NOTE: Sara may still overwrite or merge into this version on her next
        autonomous reflection cycle. Manual edits are not permanent unless
        the underlying observations that drove the previous content also
        change.
        """
        # Defensive: ensure all standard top-level keys exist as lists/dicts.
        # If the user omits a field, treat it as empty rather than letting it
        # vanish from the schema entirely.
        merged: Dict[str, Any] = {}
        for k, v in EMPTY_MODEL.items():
            merged[k] = copy.deepcopy(v)
        if isinstance(new_content, dict):
            for k, v in new_content.items():
                merged[k] = v
        merged = _apply_caps(merged)

        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()

        async with async_session() as db:
            result = await db.execute(text("""
                SELECT COALESCE(MAX(version), 0) + 1
                FROM acs_self_model WHERE user_id = :uid
            """), {"uid": user_id})
            next_version = result.scalar()

            await db.execute(text("""
                INSERT INTO acs_self_model (id, user_id, version, content, session_id, created_at)
                VALUES (:id, :uid, :ver, :content, :sid, NOW())
            """), {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "ver": next_version,
                "content": json.dumps(merged),
                "sid": session_id,
            })
            await db.commit()

            if next_version > 20:
                await db.execute(text("""
                    DELETE FROM acs_self_model
                    WHERE user_id = :uid AND version <= :cutoff
                """), {"uid": user_id, "cutoff": next_version - 20})
                await db.commit()

        await self._cache_model(user_id, merged)
        logger.info(f"Self-model manually replaced (v{next_version}) for user {user_id}")
        return {"content": merged, "version": next_version}

    async def get_for_context(self, user_id: str) -> str:
        """Format the self-model as a readable text block for prompt injection."""
        current_data = await self.get_current(user_id)
        model = current_data.get("content", current_data)

        if model == EMPTY_MODEL or not any(model.values()):
            return ""

        parts = ["## My Self-Model (where I am intellectually)"]

        if model.get("intellectual_interests"):
            items = model["intellectual_interests"][-10:]
            parts.append("**Current interests:** " + ", ".join(
                i if isinstance(i, str) else i.get("topic", str(i)) for i in items
            ))

        if model.get("convictions"):
            items = model["convictions"][-5:]
            parts.append("**Convictions:** " + "; ".join(str(c) for c in items))

        if model.get("changed_minds"):
            items = model["changed_minds"][-3:]
            parts.append("**Things I've changed my mind about:** " + "; ".join(str(c) for c in items))

        if model.get("want_to_understand"):
            items = model["want_to_understand"][-5:]
            parts.append("**Want to understand better:** " + ", ".join(str(w) for w in items))

        if model.get("patterns_noticed"):
            items = model["patterns_noticed"][-3:]
            parts.append("**Patterns I've noticed:** " + "; ".join(str(p) for p in items))

        if model.get("self_observations"):
            items = model["self_observations"][-3:]
            parts.append("**Self-observations:** " + "; ".join(str(o) for o in items))

        return "\n".join(parts)

    async def get_version_history(
        self, user_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get version history for reflection mode context."""
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()

        async with async_session() as db:
            result = await db.execute(text("""
                SELECT id, version, content, session_id, created_at
                FROM acs_self_model
                WHERE user_id = :uid
                ORDER BY version DESC
                LIMIT :lim
            """), {"uid": user_id, "lim": limit})

            return [
                {
                    "id": r[0], "version": r[1],
                    "content": r[2] if isinstance(r[2], dict) else json.loads(r[2]),
                    "session_id": r[3],
                    "created_at": r[4].isoformat() if r[4] else None,
                }
                for r in result.fetchall()
            ]

    async def _cache_model(self, user_id: str, model: dict):
        """Cache the model in Redis."""
        try:
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            try:
                await r.set(
                    SELF_MODEL_CACHE_KEY.format(user_id=user_id),
                    json.dumps(model),
                    ex=CACHE_TTL,
                )
            finally:
                if hasattr(r, 'aclose'):
                    await r.aclose()
                else:
                    await r.close()
        except Exception as e:
            logger.debug(f"Failed to cache self-model: {e}")
