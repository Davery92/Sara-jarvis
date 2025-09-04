from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.llm import LLMClient, llm_client

router = APIRouter()


class AISettingsResponse(BaseModel):
    openai_base_url: str
    openai_model: str
    openai_notification_model: Optional[str] = None
    embedding_base_url: str
    embedding_model: str
    embedding_dimension: int


class AISettingsUpdate(BaseModel):
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    openai_notification_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None


@router.get("/ai", response_model=AISettingsResponse)
async def get_ai_settings(current_user=Depends(get_current_user)):
    return AISettingsResponse(
        openai_base_url=settings.openai_base_url,
        openai_model=settings.openai_model,
        openai_notification_model=getattr(settings, "openai_notification_model", None),
        embedding_base_url=settings.embedding_base_url,
        embedding_model=settings.embedding_model,
        embedding_dimension=settings.embedding_dim,
    )


@router.put("/ai")
async def update_ai_settings(payload: AISettingsUpdate, current_user=Depends(get_current_user)):
    updated: Dict[str, Any] = {}

    if payload.openai_base_url is not None:
        settings.openai_base_url = payload.openai_base_url
        updated["openai_base_url"] = payload.openai_base_url
    if payload.openai_model is not None:
        settings.openai_model = payload.openai_model
        updated["openai_model"] = payload.openai_model
    if payload.openai_notification_model is not None:
        # Settings may or may not have this attribute; set dynamically
        setattr(settings, "openai_notification_model", payload.openai_notification_model)
        updated["openai_notification_model"] = payload.openai_notification_model
    if payload.embedding_base_url is not None:
        settings.embedding_base_url = payload.embedding_base_url
        updated["embedding_base_url"] = payload.embedding_base_url
    if payload.embedding_model is not None:
        settings.embedding_model = payload.embedding_model
        updated["embedding_model"] = payload.embedding_model
    if payload.embedding_dimension is not None:
        settings.embedding_dim = payload.embedding_dimension
        updated["embedding_dimension"] = payload.embedding_dimension

    # Reinitialize LLM client with new base/model
    global llm_client  # type: ignore
    llm_client = LLMClient()

    return {"message": "AI settings updated", "updated_settings": updated}


@router.post("/ai/test")
async def test_ai_settings(current_user=Depends(get_current_user)):
    results: Dict[str, Any] = {}

    # Test LLM chat
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.openai_base_url}/chat/completions",
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "Reply with: Connection successful"},
                    ],
                    "max_tokens": 10,
                },
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
            results["llm"] = {"status": "ok" if resp.status_code == 200 else "error", "code": resp.status_code}
    except Exception as e:
        results["llm"] = {"status": "error", "message": str(e)}

    # Test embeddings
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.embedding_base_url}/v1/embeddings",
                json={"model": settings.embedding_model, "input": "test"},
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
            ok = resp.status_code == 200
            dim_ok = False
            if ok:
                data = resp.json()
                emb = data.get("data", [{}])[0].get("embedding", [])
                dim_ok = isinstance(emb, list) and len(emb) == settings.embedding_dim
            results["embedding"] = {"status": "ok" if ok and dim_ok else "error", "code": resp.status_code}
    except Exception as e:
        results["embedding"] = {"status": "error", "message": str(e)}

    return results

