"""
BGE Reranker Service
Reranks retrieval results using BGE reranker model
"""
from typing import List, Tuple, Optional
import logging
import asyncio

logger = logging.getLogger(__name__)


class BGEReranker:
    """Reranks results using BGE reranker model"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base", use_local: bool = True):
        self.model_name = model_name
        self.use_local = use_local
        self.model = None
        self.tokenizer = None
        self._initialized = False

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
                logger.warning("Remote reranking not implemented yet, using fallback")
                self._initialized = False

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
            return [0.5] * len(pairs)

        try:
            # Run prediction in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            scores = await loop.run_in_executor(
                None,
                self._predict_sync,
                pairs
            )
            return scores

        except Exception as e:
            logger.error(f"Error during reranking: {e}")
            return [0.5] * len(pairs)

    def _predict_sync(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Synchronous prediction (runs in executor)"""
        if not self.model:
            return [0.5] * len(pairs)

        scores = self.model.predict(pairs)

        # Normalize scores to 0-1 range
        # BGE reranker typically outputs scores in range [-10, 10]
        normalized = [(float(score) + 10) / 20 for score in scores]

        return normalized

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


async def get_reranker(model_name: str = "BAAI/bge-reranker-base") -> BGEReranker:
    """
    Get or create global reranker instance

    Args:
        model_name: BGE reranker model name

    Returns:
        Initialized BGEReranker instance
    """
    global _global_reranker

    if _global_reranker is None:
        _global_reranker = BGEReranker(model_name=model_name)
        await _global_reranker.initialize()

    return _global_reranker
