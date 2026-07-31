"""
Embedding service for generating semantic embeddings using BGE-M3 model.
Supports individual text embedding and batch processing.
"""
import httpx
import logging
from typing import List, Optional, Tuple
from urllib.parse import urlparse
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        # Note: no persistent client. We open a fresh httpx.AsyncClient per call below
        # to avoid the httpx 0.25 / httpcore 1.0 "All connection attempts failed" bug
        # that fires when a pooled connection is reused after its source loop is gone.
        pass

    def _get_current_settings(self, capability: str = "embedding") -> Tuple[str, str, int]:
        """Get current settings dynamically so runtime updates work.

        Presence-latency follow-up, ruling 1 (2026-07-31): resolves through
        the model broker's capability classes so presence ("embedding",
        the fast GPU host) and background cognition ("embedding_cognition",
        the local CPU fallback container) route to different hosts and can
        never queue behind each other — same fix already applied to chat's
        own model routing, one layer down."""
        try:
            from app.services.llm_broker import resolve as _resolve_capability
            cap = _resolve_capability(capability)
            base = (cap.get("base_url") or "").strip().rstrip("/")
            model = cap.get("model") or settings.embedding_model
        except Exception as e:
            logger.debug(f"[embedding] broker resolve failed for {capability!r}, falling back: {e}")
            base = (settings.embedding_base_url or "").strip().rstrip("/")
            model = settings.embedding_model
        try:
            p = urlparse(base)
            if not p.scheme or not p.netloc:
                logger.warning("Embedding base URL invalid or empty; falling back to openai_base_url")
                base = (settings.openai_base_url or "").rstrip("/")
        except Exception:
            base = (settings.openai_base_url or "").rstrip("/")
        # Strip /v1 suffix — this service appends /v1/embeddings itself
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        return base, model, settings.embedding_dim

    async def generate_embedding(self, text: str, capability: str = "embedding") -> Optional[List[float]]:
        """Generate embedding for text using BGE-M3 model.

        `capability`: "embedding" (default) for real chat turns — the fast
        GPU host; "embedding_cognition" for background/non-interactive work
        (consolidation, PKG ingestion, lesson matching) — the local CPU
        fallback container. Passing the wrong one for a presence-critical
        call silently reintroduces the exact contention this split fixes.

        Presence-latency follow-up, ruling 1 (2026-07-31) second win: a
        short Redis cache keyed by exact text — repeated text produces an
        identical vector regardless of which host generated it (same
        model/weights either side of the presence/cognition split), so a
        turn that re-embeds the same query (e.g. a quick back-and-forth
        referencing the same thing) gets a free cache hit instead of a
        real network round-trip."""
        cache_key = None
        try:
            import hashlib
            from app.services.unified_context import _get_redis
            cache_key = f"sara:embedding_cache:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
            r = await _get_redis()
            cached = await r.get(cache_key)
            if cached:
                import json as _json
                return _json.loads(cached if isinstance(cached, str) else cached.decode("utf-8"))
        except Exception as e:
            logger.debug(f"[embedding] cache read skipped: {e}")

        try:
            # Get current settings dynamically for runtime updates to work
            base_url, model, dimension = self._get_current_settings(capability)

            # NOTE: httpx 0.25 + httpcore 1.0 inside the long-running uvicorn process
            # was raising "All connection attempts failed" (ConnectError) intermittently
            # for *only* the backend process — celery workers on the same docker network
            # had no trouble. Probing the same hostname from `docker exec ... python3 -c`
            # also worked. To sidestep the bug we use sync `requests` in a thread.
            import asyncio
            import requests

            url = f"{base_url}/v1/embeddings"
            payload = {"model": model, "input": text, "encoding_format": "float"}
            headers = {"Authorization": f"Bearer {settings.openai_api_key}"}

            def _post():
                return requests.post(url, json=payload, headers=headers, timeout=60)

            last_exc: Optional[Exception] = None
            response = None
            for attempt in range(3):
                try:
                    response = await asyncio.to_thread(_post)
                    break
                except (requests.ConnectionError, requests.Timeout) as e:
                    last_exc = e
                    if attempt < 2:
                        await asyncio.sleep(0.3 * (attempt + 1))
                    continue
            if response is None:
                raise last_exc or RuntimeError("embedding request failed without exception")
            response.raise_for_status()

            result = response.json()
            embedding = result["data"][0]["embedding"]

            # Ensure the embedding has the correct dimension
            actual_dim = len(embedding)
            if actual_dim != dimension:
                action = "Padding" if actual_dim < dimension else "Truncating"
                logger.warning(
                    f"Embedding dimension mismatch from {model}: expected {dimension}, got {actual_dim}. "
                    f"{action} to match configured dimension."
                )
                # Pad or truncate to match expected dimension
                if actual_dim < dimension:
                    embedding.extend([0.0] * (dimension - actual_dim))
                else:
                    embedding = embedding[:dimension]

            if cache_key:
                try:
                    import json as _json
                    from app.services.unified_context import _get_redis as _get_redis_w
                    r = await _get_redis_w()
                    await r.set(cache_key, _json.dumps(embedding), ex=3600)
                except Exception as e:
                    logger.debug(f"[embedding] cache write skipped: {e}")

            return embedding

        except Exception as e:
            logger.error(f"Error generating embedding [{type(e).__name__}]: {e}")
            return None
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts.

        Returns:
            List of embeddings, with None for any texts that failed to embed.
            Callers should handle None values appropriately (skip, retry, etc.)
        """
        try:
            # For now, process individually to avoid API limits
            embeddings: List[Optional[List[float]]] = []
            failed_count = 0

            for i, text in enumerate(texts):
                embedding = await self.generate_embedding(text)
                if embedding:
                    embeddings.append(embedding)
                else:
                    # Return None for failed embeddings - let callers decide how to handle
                    logger.warning(f"Failed to generate embedding for text {i+1}/{len(texts)} (length={len(text)})")
                    embeddings.append(None)
                    failed_count += 1

            if failed_count > 0:
                logger.warning(f"Batch embedding completed with {failed_count}/{len(texts)} failures")

            return embeddings

        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}", exc_info=True)
            # Return all None values so callers know everything failed
            return [None] * len(texts)

# Global embedding service instance
embedding_service = EmbeddingService()