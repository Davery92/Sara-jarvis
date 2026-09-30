"""Thin, raise-on-failure facade over `embedding_service`.

Cleanup plan Phase 3.1. This module used to own a second embedding engine of
its own, wrapping `core.llm.llm_client.get_embedding`, which reads
`settings.embedding_base_url` directly and so bypassed the model broker's
capability split entirely. That split exists because presence work ("embedding",
the fast GPU host at 10.185.1.8) and background cognition
("embedding_cognition", the local CPU container) must never queue behind each
other — a module that routes around it silently reintroduces exactly the
contention the split was added to fix, and that is the bug class behind the
GPU/CPU embedding mixup.

`embedding_service.py` is the only engine now. Everything here delegates.

Two deliberate differences from the service's own API, both preserving the
behavior the 16 call sites of this module already depend on:

* **These functions RAISE; the service returns None.** `generate_embedding`
  reports failure as `None`, which a caller who was written against this
  module would happily store as an embedding. So a `None` from the service
  becomes an `EmbeddingUnavailable` here. Callers are unchanged.
* **Batch stays parallel.** `generate_embeddings_batch` is a sequential `for`
  loop, so delegating to it would turn every batch call site's parallel fan-out
  into serial round-trips. This keeps the `asyncio.gather` the old
  implementation had.

`capability` defaults to "embedding", which resolves to the same host
`settings.embedding_base_url` already pointed at — so routing is unchanged for
every existing caller. Background/non-interactive callers (consolidation, PKG
ingestion, lesson matching) should pass "embedding_cognition" explicitly; that
is now possible from here, which it was not before.
"""
import asyncio
import logging
from typing import List

from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class EmbeddingUnavailable(RuntimeError):
    """The embedding backend produced no vector.

    Raised in place of returning a falsy embedding, because every caller of
    this module predates `embedding_service` and treats a return value as a
    usable vector.
    """


async def get_embedding(text: str, capability: str = "embedding") -> List[float]:
    """Embedding for a single text. Raises if the backend produced none."""
    embedding = await embedding_service.generate_embedding(text, capability=capability)
    if not embedding:
        raise EmbeddingUnavailable(
            f"embedding backend returned no vector for capability {capability!r} "
            f"(text length {len(text)})"
        )
    return embedding


async def get_embeddings_batch(texts: List[str], capability: str = "embedding") -> List[List[float]]:
    """Embeddings for several texts, in parallel. Raises if any one fails."""
    if not texts:
        return []
    return await asyncio.gather(*(get_embedding(t, capability=capability) for t in texts))


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 150) -> List[str]:
    """Split text into overlapping chunks.

    Unrelated to embedding transport and deliberately left here rather than
    moved: it is pure text handling with its own callers, and moving it would
    have touched import sites this pass is not rewriting.
    """
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
