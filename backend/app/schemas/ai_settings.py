"""Pydantic schemas for AI settings endpoints."""
from typing import Optional

from pydantic import BaseModel


class AISettingsResponse(BaseModel):
    ai_provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    openai_notification_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None
    bg_llm_primary_url: Optional[str] = None
    bg_llm_primary_model: Optional[str] = None
    bg_llm_fallback_url: Optional[str] = None
    bg_llm_fallback_model: Optional[str] = None


class AISettingsUpdate(BaseModel):
    ai_provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    openai_notification_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None
    bg_llm_primary_url: Optional[str] = None
    bg_llm_primary_model: Optional[str] = None
    bg_llm_fallback_url: Optional[str] = None
    bg_llm_fallback_model: Optional[str] = None
