"""
Embedding service for generating semantic embeddings using BGE-M3 model.
Supports individual text embedding and batch processing.
"""
import httpx
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

# Configuration
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://100.104.68.115:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

class EmbeddingService:
    def __init__(self):
        self.client = httpx.AsyncClient()
        self.base_url = EMBEDDING_BASE_URL
        self.model = EMBEDDING_MODEL
        self.dimension = EMBEDDING_DIM
    
    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using BGE-M3 model"""
        try:
            # Use the embeddings endpoint
            response = await self.client.post(
                f"{self.base_url}/v1/embeddings",
                json={
                    "model": self.model,
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
            if len(embedding) != self.dimension:
                logger.warning(f"Expected embedding dimension {self.dimension}, got {len(embedding)}")
                # Pad or truncate to match expected dimension
                if len(embedding) < self.dimension:
                    embedding.extend([0.0] * (self.dimension - len(embedding)))
                else:
                    embedding = embedding[:self.dimension]
            
            return embedding
            
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        try:
            # For now, process individually to avoid API limits
            embeddings = []
            for text in texts:
                embedding = await self.generate_embedding(text)
                if embedding:
                    embeddings.append(embedding)
                else:
                    # Return zero vector for failed embeddings
                    embeddings.append([0.0] * self.dimension)
            return embeddings
            
        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            return [[0.0] * self.dimension] * len(texts)

# Global embedding service instance
embedding_service = EmbeddingService()