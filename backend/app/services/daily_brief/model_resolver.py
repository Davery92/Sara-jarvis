"""
Helpers for resolving the canonical background model label for daily brief jobs.
"""
import os
from typing import Optional


def resolve_qwen_122_model_label(*preferred_models: Optional[str]) -> str:
    """
    Resolve the background model label for daily brief synthesis.

    Preference order:
    1. Explicit preferred candidates passed by caller
    2. Background model settings (runtime + env-backed)
    3. Primary chat model settings
    4. MLX default
    """
    from app.core.config import settings
    from app.core.llm_config import llm_config

    candidates = [
        *preferred_models,
        getattr(settings, "bg_llm_primary_model", None),
        getattr(settings, "openai_model", None),
        llm_config.bg_primary_model,
        llm_config.primary_model,
        os.getenv("BG_LLM_PRIMARY_MODEL"),
        os.getenv("OPENAI_MODEL"),
    ]

    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()

    return "qwen3.8-27b"
