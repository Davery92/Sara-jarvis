"""
BGE Reranker Service
Reranks retrieval results using BGE reranker model
"""
from typing import List, Tuple, Optional
import logging
import asyncio
import os
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Interval (seconds) between rate-limited WARNING logs when the reranker
# falls back to neutral 0.5 scores. Without this, a cold or broken reranker
# silently degrades ranking for every query.
_FALLBACK_LOG_INTERVAL_SEC = 60.0


class BGEReranker:
    """Reranks results using BGE reranker model"""

    # Class-level counters exposed so callers (e.g. a /debug endpoint) can
    # see cumulative degraded-retrieval counts without holding a reference
    # to a specific instance.
    _fallback_count: int = 0
    _fallback_last_logged: float = 0.0
    _fallback_reasons: dict = {}

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        use_local: bool = True,
        remote_base_url: Optional[str] = None,
        remote_model: Optional[str] = None,
    ):
        self.model_name = model_name
        self.use_local = use_local
        self.model = None
        self.tokenizer = None
        self._initialized = False
        self.remote_base_url = (remote_base_url or "").rstrip("/")
        self.remote_model = remote_model or settings.reranker_model

    @classmethod
    def _note_fallback(cls, reason: str, n_pairs: int) -> None:
        """Record a neutral-score fallback and emit a rate-limited WARNING.

        Keeps a per-reason counter so the operator can tell whether we're
        degrading because the model never loaded, prediction raised, or the
        remote endpoint is flaky.
        """
        cls._fallback_count += 1
        cls._fallback_reasons[reason] = cls._fallback_reasons.get(reason, 0) + 1
        now = time.monotonic()
        if now - cls._fallback_last_logged >= _FALLBACK_LOG_INTERVAL_SEC:
            cls._fallback_last_logged = now
            top = sorted(cls._fallback_reasons.items(), key=lambda kv: -kv[1])[:3]
            reasons_str = ", ".join(f"{r}={c}" for r, c in top)
            logger.warning(
                "BGE reranker degraded: %d fallback calls so far (most recent reason=%s, %d pairs). "
                "Top reasons: %s",
                cls._fallback_count, reason, n_pairs, reasons_str,
            )

    @classmethod
    def get_stats(cls) -> dict:
        """Return cumulative fallback stats for observability endpoints."""
        return {
            "fallback_count": cls._fallback_count,
            "fallback_reasons": dict(cls._fallback_reasons),
            "last_logged_monotonic": cls._fallback_last_logged,
        }

    async def initialize(self):
        """Initialize the reranker model"""
        if self._initialized:
            return

        try:
            if self.use_local:
                # Try to use sentence-transformers for local reranking
                try:
                    from sentence_transformers import CrossEncoder

                    logger.info(f"Loading BGE reranker model: {self.model_name}")
                    self.model = CrossEncoder(self.model_name)
                    self._initialized = True
                    logger.info("✅ BGE reranker initialized successfully")

                except ImportError:
                    logger.warning("sentence-transformers not available, reranking will use fallback scoring")
                    self._initialized = False
                except Exception as e:
                    logger.error(f"Failed to load reranker model: {e}")
                    self._initialized = False
            else:
                if not self.remote_base_url:
                    logger.warning("Remote reranking configured without base URL, using fallback")
                    self._initialized = False
                else:
                    logger.info(
                        f"✅ BGE reranker remote mode enabled: {self.remote_base_url} ({self.remote_model})"
                    )
                    self._initialized = True

        except Exception as e:
            logger.error(f"Error initializing reranker: {e}")
            self._initialized = False

    async def predict(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """
        Predict reranking scores for query-document pairs

        Args:
            pairs: List of (query, document) tuples

        Returns:
            List of reranking scores
        """
        if not self._initialized:
            # Fallback: return neutral scores
            self._note_fallback("not_initialized", len(pairs))
            return [0.5] * len(pairs)

        try:
            if self.use_local:
                # Run prediction in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                scores = await loop.run_in_executor(
                    None,
                    self._predict_sync,
                    pairs
                )
                return scores

            return await self._predict_remote(pairs)

        except Exception as e:
            logger.error(f"Error during reranking: {e}")
            self._note_fallback(f"exception:{type(e).__name__}", len(pairs))
            return [0.5] * len(pairs)

    def _predict_sync(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Synchronous prediction (runs in executor)"""
        if not self.model:
            self._note_fallback("local_model_none", len(pairs))
            return [0.5] * len(pairs)

        scores = self.model.predict(pairs)

        # Normalize scores to 0-1 range
        # BGE reranker typically outputs scores in range [-10, 10]
        normalized = [(float(score) + 10) / 20 for score in scores]

        return normalized

    @staticmethod
    def _normalize_remote_score(score: float) -> float:
        """
        Normalize remote reranker score to [0, 1].
        Handles both normalized scores and raw cross-encoder style scores.
        """
        if 0.0 <= score <= 1.0:
            return score
        if -10.0 <= score <= 10.0:
            return (score + 10.0) / 20.0
        return max(0.0, min(1.0, score))

    async def _predict_remote(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Remote prediction via OpenAI-compatible /v1/rerank endpoint."""
        if not self.remote_base_url:
            self._note_fallback("remote_no_base_url", len(pairs))
            return [0.5] * len(pairs)

        if not pairs:
            return []

        scores = [0.5] * len(pairs)
        any_group_failed = False

        # Group by query to avoid one request per pair.
        grouped: dict[str, list[tuple[int, str]]] = {}
        for idx, (query, doc) in enumerate(pairs):
            grouped.setdefault(query, []).append((idx, doc))

        timeout = httpx.Timeout(15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for query, indexed_docs in grouped.items():
                documents = [doc for _, doc in indexed_docs]
                payload = {
                    "model": self.remote_model,
                    "query": query,
                    "documents": documents,
                    "top_n": len(documents),
                }
                try:
                    resp = await client.post(f"{self.remote_base_url}/v1/rerank", json=payload)
                    resp.raise_for_status()
                    data = resp.json() or {}
                    for item in data.get("results", []):
                        doc_index = item.get("index")
                        relevance = item.get("relevance_score")
                        if doc_index is None or relevance is None:
                            continue
                        if 0 <= int(doc_index) < len(indexed_docs):
                            original_idx = indexed_docs[int(doc_index)][0]
                            scores[original_idx] = self._normalize_remote_score(float(relevance))
                except Exception as e:
                    logger.warning(f"Remote rerank request failed for query group: {e}")
                    any_group_failed = True
                    # Keep neutral fallback for this group.

        if any_group_failed:
            self._note_fallback("remote_http_failure", len(pairs))
        return scores

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None
    ) -> List[Tuple[int, float]]:
        """
        Rerank documents by relevance to query

        Args:
            query: Search query
            documents: List of documents to rank
            top_k: Return only top K results (None = all)

        Returns:
            List of (index, score) tuples sorted by score descending
        """
        if not documents:
            return []

        # Create query-document pairs
        pairs = [(query, doc) for doc in documents]

        # Get scores
        scores = await self.predict(pairs)

        # Create (index, score) pairs and sort
        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        # Return top_k if specified
        if top_k is not None:
            indexed_scores = indexed_scores[:top_k]

        return indexed_scores


# Global reranker instance
_global_reranker: Optional[BGEReranker] = None


async def get_reranker(
    model_name: str = "BAAI/bge-reranker-base",
    use_local: Optional[bool] = None,
) -> BGEReranker:
    """
    Get or create global reranker instance

    Args:
        model_name: BGE reranker model name

    Returns:
        Initialized BGEReranker instance
    """
    global _global_reranker

    if _global_reranker is None:
        if use_local is None:
            use_local = os.getenv("BGE_RERANKER_REMOTE", "false").lower() != "true"

        reranker_base = (settings.reranker_base_url or settings.embedding_base_url or "").rstrip("/")
        _global_reranker = BGEReranker(
            model_name=model_name,
            use_local=use_local,
            remote_base_url=reranker_base,
            remote_model=settings.reranker_model,
        )
        await _global_reranker.initialize()

    return _global_reranker
