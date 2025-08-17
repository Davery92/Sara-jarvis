import asyncio
import logging
from typing import List, Union
from app.core.llm import llm_client

logger = logging.getLogger(__name__)


async def get_embedding(text: str) -> List[float]:
    """Get embedding for a single text"""
    try:
        return await llm_client.get_embedding(text)
    except Exception as e:
        logger.error(f"Failed to get embedding: {e}")
        raise


async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Get embeddings for multiple texts in batch"""
    try:
        # Process in parallel for better performance
        tasks = [get_embedding(text) for text in texts]
        embeddings = await asyncio.gather(*tasks)
        return embeddings
    except Exception as e:
        logger.error(f"Failed to get batch embeddings: {e}")
        raise


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 150) -> List[str]:
    """Split text into overlapping chunks"""
    
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # If this is not the last chunk, try to break at a sentence or word boundary
        if end < len(text):
            # Look for sentence boundary
            sentence_break = text.rfind('.', start, end)
            if sentence_break > start + chunk_size // 2:
                end = sentence_break + 1
            else:
                # Look for word boundary
                word_break = text.rfind(' ', start, end)
                if word_break > start + chunk_size // 2:
                    end = word_break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # Move start forward, with overlap
        start = end - overlap
        if start >= len(text):
            break
    
    return chunks