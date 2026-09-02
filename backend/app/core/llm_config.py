"""
Centralized LLM Configuration

Single source of truth for all model names, endpoints, and LLM-related settings.
Import from here instead of hardcoding model names or endpoints.

Usage:
    from app.core.llm_config import llm_config

    url = llm_config.primary_url
    model = llm_config.primary_model
    fast_model = llm_config.fast_model
"""
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LLMConfig:
    """Immutable LLM configuration loaded from environment with sensible defaults."""

    # Primary LLM (chat, tool use, main interactions)
    primary_url: str = field(default_factory=lambda: os.getenv(
        "OPENAI_BASE_URL", "http://100.104.68.115:8082/v1"))  # chat lane (:8082); bg lane :8081
    primary_model: str = field(default_factory=lambda: os.getenv(
        "OPENAI_MODEL", "qwen3.8-27b"))

    # Fallback LLM (used when primary is down)
    fallback_url: str = field(default_factory=lambda: os.getenv(
        "LLM_FALLBACK_URL", "http://10.185.1.8:8686/v1"))
    fallback_model: str = field(default_factory=lambda: os.getenv(
        "LLM_FALLBACK_MODEL", "Qwen3.5-35B-A3B"))

    # Fast model (lightweight tasks: scoring, classification, extraction)
    fast_model: str = field(default_factory=lambda: os.getenv(
        "FAST_MODEL", "Qwen3.5-35B-A3B"))
    fast_model_url: str = field(default_factory=lambda: os.getenv(
        "FAST_MODEL_URL", "http://10.185.1.8:8686/v1"))

    # Background LLM (autonomy, deliberation, background tasks)
    bg_primary_url: str = field(default_factory=lambda: os.getenv(
        "BG_LLM_PRIMARY_URL", "http://100.104.68.115:8081/v1"))
    bg_primary_model: str = field(default_factory=lambda: os.getenv(
        "BG_LLM_PRIMARY_MODEL", "qwen3.8-27b"))
    bg_fallback_url: str = field(default_factory=lambda: os.getenv(
        "BG_LLM_FALLBACK_URL", "http://10.185.1.8:8686/v1"))
    bg_fallback_model: str = field(default_factory=lambda: os.getenv(
        "BG_LLM_FALLBACK_MODEL", "Qwen3.5-35B-A3B"))

    # Embedding
    embedding_url: str = field(default_factory=lambda: os.getenv(
        "EMBEDDING_BASE_URL", "http://10.185.1.8:11434"))
    embedding_model: str = field(default_factory=lambda: os.getenv(
        "EMBEDDING_MODEL", "bge-m3"))

    # Vision (OpenAI-compatible llama.cpp / vLLM / Ollama with VL).
    # The endpoint can be either a llama.cpp-style server (/v1/chat/completions
    # with image_url content parts) or a classic Ollama server (/api/chat with
    # an images array). routes/vision.py picks the right caller per-flow.
    vision_url: str = field(default_factory=lambda: os.getenv(
        "VISION_ENDPOINT", "http://10.185.1.8:8686"))
    vision_model: str = field(default_factory=lambda: os.getenv(
        "VISION_MODEL", "qwen3.6-35b-a3b"))

    # Reranker
    reranker_url: str = field(default_factory=lambda: os.getenv(
        "RERANKER_BASE_URL", "http://10.185.1.8:11434"))
    reranker_model: str = field(default_factory=lambda: os.getenv(
        "RERANKER_MODEL", "bge-reranker-v2-m3:latest"))

    # Timeouts
    request_timeout: float = 60.0
    bg_request_timeout: float = 180.0
    connect_timeout: float = 6.0
    health_check_timeout: float = 5.0


# Module-level singleton — import this
llm_config = LLMConfig()
