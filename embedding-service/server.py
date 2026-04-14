"""Minimal OpenAI-compatible embedding service using sentence-transformers.

Runs bge-m3 locally on CPU. Exposes /v1/embeddings endpoint.
Model is loaded once at startup and kept in memory (~670MB).
"""

import logging
import time
from typing import List, Optional

import numpy as np
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("embedding-service")

app = FastAPI(title="Embedding Service")

# Load model at startup
MODEL_NAME = "BAAI/bge-m3"
logger.info(f"Loading model {MODEL_NAME}...")
t0 = time.time()
model = SentenceTransformer(MODEL_NAME)
logger.info(f"Model loaded in {time.time() - t0:.1f}s")


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: Optional[str] = "bge-m3"


class EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: List[float]
    index: int


class EmbeddingUsage(BaseModel):
    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[EmbeddingData]
    model: str
    usage: EmbeddingUsage


@app.post("/v1/embeddings")
async def create_embedding(request: EmbeddingRequest) -> EmbeddingResponse:
    texts = [request.input] if isinstance(request.input, str) else request.input

    embeddings = model.encode(texts, normalize_embeddings=True)

    data = []
    total_tokens = 0
    for i, (text, emb) in enumerate(zip(texts, embeddings)):
        data.append(EmbeddingData(
            embedding=emb.tolist(),
            index=i,
        ))
        total_tokens += len(text.split())

    return EmbeddingResponse(
        data=data,
        model=request.model or "bge-m3",
        usage=EmbeddingUsage(prompt_tokens=total_tokens, total_tokens=total_tokens),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8100)
