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
        self.client = httpx.AsyncClient()

    def _get_current_settings(self) -> Tuple[str, str, int]:
        """Get current settings dynamically so runtime updates work"""
        base = (settings.embedding_base_url or "").strip().rstrip("/")
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
        return base, settings.embedding_model, settings.embedding_dim

    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using BGE-M3 model"""
        try:
            # Get current settings dynamically for runtime updates to work
            base_url, model, dimension = self._get_current_settings()

            # Use the embeddings endpoint
            response = await self.client.post(
                f"{base_url}/v1/embeddings",
                json={
                    "model": model,
                    "input": text,
                    "encoding_format": "float"
                },
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                timeout=30.0
            )
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

            return embedding

        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
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