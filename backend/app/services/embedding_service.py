"""
Embedding service for generating semantic embeddings using BGE-M3 model.
Supports individual text embedding and batch processing.
"""
import httpx
import logging
from typing import List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        self.client = httpx.AsyncClient()

    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using BGE-M3 model"""
        try:
            # Read settings dynamically so runtime updates work
            base_url = settings.embedding_base_url
            model = settings.embedding_model
            dimension = settings.embedding_dim

            # Use the embeddings endpoint
            response = await self.client.post(
                f"{base_url}/v1/embeddings",
                json={
                    "model": model,
                    "input": text,
                    "encoding_format": "float"
                },
                headers={"Authorization": "Bearer dummy"},
                timeout=30.0
            )
            response.raise_for_status()

            result = response.json()
            embedding = result["data"][0]["embedding"]

            # Ensure the embedding has the correct dimension
            if len(embedding) != dimension:
                logger.warning(f"Expected embedding dimension {dimension}, got {len(embedding)}")
                # Pad or truncate to match expected dimension
                if len(embedding) < dimension:
                    embedding.extend([0.0] * (dimension - len(embedding)))
                else:
                    embedding = embedding[:dimension]

            return embedding

        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        try:
            # Read dimension dynamically
            dimension = settings.embedding_dim

            # For now, process individually to avoid API limits
            embeddings = []
            for text in texts:
                embedding = await self.generate_embedding(text)
                if embedding:
                    embeddings.append(embedding)
                else:
                    # Return zero vector for failed embeddings
                    embeddings.append([0.0] * dimension)
            return embeddings

        except Exception as e:
            # Read dimension dynamically for error case
            dimension = settings.embedding_dim
            logger.error(f"Error generating batch embeddings: {e}")
            return [[0.0] * dimension] * len(texts)

# Global embedding service instance
embedding_service = EmbeddingService()