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
    bg_llm_request_timeout: Optional[float] = None
    bg_llm_connect_timeout: Optional[float] = None
    bg_llm_num_ctx: Optional[int] = None
    codex_oauth_connected: Optional[bool] = None
    codex_oauth_email: Optional[str] = None
    codex_oauth_expires_at: Optional[str] = None
    codex_oauth_account_id: Optional[str] = None
    vm_sandbox_host: Optional[str] = None
    vm_sandbox_username: Optional[str] = None
    vm_sandbox_ssh_key_path: Optional[str] = None


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
    bg_llm_request_timeout: Optional[float] = None
    bg_llm_connect_timeout: Optional[float] = None
    bg_llm_num_ctx: Optional[int] = None
    vm_sandbox_host: Optional[str] = None
    vm_sandbox_username: Optional[str] = None
    vm_sandbox_ssh_key_path: Optional[str] = None
