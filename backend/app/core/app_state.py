"""
Centralized mutable application state.

All module-level globals from main_simple.py that get mutated at runtime
(by settings routes, OAuth flows, startup hooks, etc.) live here as a singleton.

This enables extracting functions and classes from main_simple.py because they
can accept/import app_state instead of reading bare module globals.
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class AppState:
    """Singleton holding all mutable runtime configuration."""

    def __init__(self):
        # ── Core identity ──
        self.assistant_name: str = os.getenv("ASSISTANT_NAME", "Sara")
        self.database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@db:5432/sara_hub")

        # ── AI Provider ──
        self.ai_provider: str = os.getenv("AI_PROVIDER", "local")
        self.openai_base_url: str = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:8081/v1")
        self.openai_model: str = os.getenv("OPENAI_MODEL", "Qwen3.5-35B-A3B")
        # Default model for the interactive chat selector, decoupled from the
        # shared `openai_model` above (which many background/utility services
        # reuse). Kept separate so the chat can default to a reasoning-only
        # Claude model (Sonnet 5) without forcing every utility LLM call — most
        # of which send `temperature` — onto a model that would 400 on it.
        self.chat_default_model: str = os.getenv("CHAT_DEFAULT_MODEL", "claude-sonnet-5")
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "dummy")
        self.anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
        self.google_api_key: str = os.getenv("GOOGLE_API_KEY", "")

        # ── Fast / Voice / Notification models ──
        self.fast_model_url: str = os.getenv("FAST_MODEL_URL", os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:8081/v1"))
        self.fast_model: str = os.getenv("FAST_MODEL", "gemini-3-flash-preview")
        self.fast_model_api_key: str = os.getenv("FAST_MODEL_API_KEY", os.getenv("OPENAI_API_KEY", ""))
        self.voice_model: str = os.getenv("VOICE_MODEL", "Qwen3.5-35B-A3B")
        self.notification_model: str = os.getenv("OPENAI_NOTIFICATION_MODEL", "Qwen3.5-35B-A3B")

        # ── Embedding ──
        self.embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "http://10.185.1.8:11434")
        self.embedding_model: str = os.getenv("EMBEDDING_MODEL", "bge-m3")
        self.embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "1024"))

        # ── Codex OAuth (mutable at runtime) ──
        self.codex_oauth_client_id: str = os.getenv("CODEX_OAUTH_CLIENT_ID", "").strip() or "app_EMoamEEZ73f0CkXaXp7hrann"
        self.codex_oauth_authorize_url: str = os.getenv("CODEX_OAUTH_AUTHORIZE_URL", "").strip() or "https://auth.openai.com/oauth/authorize"
        self.codex_oauth_token_url: str = os.getenv("CODEX_OAUTH_TOKEN_URL", "").strip() or "https://auth.openai.com/oauth/token"
        self.codex_oauth_scope: str = os.getenv("CODEX_OAUTH_SCOPE", "").strip() or "openid profile email offline_access"
        self.codex_oauth_originator: str = os.getenv("CODEX_OAUTH_ORIGINATOR", "").strip() or "codex_vscode"
        self.codex_oauth_redirect_uri: str = os.getenv("CODEX_OAUTH_REDIRECT_URI", "").strip()
        self.codex_default_base_url: str = os.getenv("CODEX_BASE_URL", "https://chatgpt.com/backend-api")
        self.codex_default_model: str = os.getenv("CODEX_DEFAULT_MODEL", "gpt-5.3-codex")
        self.codex_oauth_access_token: str = os.getenv("CODEX_OAUTH_ACCESS_TOKEN", "")
        self.codex_oauth_refresh_token: str = os.getenv("CODEX_OAUTH_REFRESH_TOKEN", "")
        self.codex_oauth_expires_at: str = os.getenv("CODEX_OAUTH_EXPIRES_AT", "")
        self.codex_oauth_account_id: str = os.getenv("CODEX_OAUTH_ACCOUNT_ID", "")
        self.codex_oauth_email: str = os.getenv("CODEX_OAUTH_EMAIL", "")

        # ── NTFY ──
        self.ntfy_server_url: str = os.getenv("NTFY_SERVER_URL", "http://10.185.1.8:8889")
        self.ntfy_enabled: bool = os.getenv("NTFY_ENABLED", "true").lower() == "true"
        self.ntfy_timers_topic: str = os.getenv("NTFY_TIMERS_TOPIC", "sara")
        self.ntfy_reminders_topic: str = os.getenv("NTFY_REMINDERS_TOPIC", "sara")
        self.ntfy_documents_topic: str = os.getenv("NTFY_DOCUMENTS_TOPIC", "sara")
        self.ntfy_system_topic: str = os.getenv("NTFY_SYSTEM_TOPIC", "sara")

        # ── CORS ──
        _cors_env = os.getenv("CORS_ORIGINS", "")
        _parsed = []
        if _cors_env:
            try:
                p = json.loads(_cors_env)
                if isinstance(p, list):
                    _parsed = [str(x) for x in p]
            except Exception:
                _parsed = [o.strip() for o in _cors_env.split(",") if o.strip()]
        self.cors_origins: List[str] = _parsed or [
            "https://sara.avery.cloud", "http://sara.avery.cloud",
            "https://canvas.avery.cloud", "http://canvas.avery.cloud",
            "http://localhost:3000", "http://localhost:3001", "http://localhost:3002",
            "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://127.0.0.1:3002",
            "http://10.185.1.180:3000", "http://10.185.1.180:3001", "http://10.185.1.180:3002",
            "http://10.185.1.188:3000", "http://10.185.1.180", "http://10.185.1.188",
        ]
        self.allowed_origin_regex: str = os.getenv("CORS_ALLOW_REGEX") or r"^https?://(10\.185\.1\.(180|188))(\:\d+)?$"

        # ── Available models for chat selector ──
        self.available_models: List[Dict[str, str]] = [
            {"id": "gpt-5.3-codex", "name": "GPT-5.3 Codex", "provider": "codex"},
            {"id": "gpt-5.3-codex-spark", "name": "GPT-5.3 Codex Spark", "provider": "codex"},
            {"id": "claude-opus-4-8", "name": "Claude Opus 4.8", "provider": "anthropic"},
            {"id": "claude-sonnet-5", "name": "Claude Sonnet 5", "provider": "anthropic"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "provider": "anthropic"},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "provider": "google"},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "google"},
            {"id": "Qwen3.5-35B-A3B", "name": "Local 35B", "provider": "local"},
            {"id": "qwen3.6-27b", "name": "Local MLX Qwen3.6 27B", "provider": "local", "base_url": "http://100.104.68.115:8081/v1"},
            {"id": "nemotron-3-nano", "name": "Nemotron Nano", "provider": "local"},
        ]

        # ── User settings defaults ──
        self.default_user_settings: Dict[str, Any] = {
            "notification_categories": {},
            "dashboard_layout": "default",
            "assistant_name": self.assistant_name,
        }

    def is_anthropic_provider(self) -> bool:
        return "api.anthropic.com" in self.openai_base_url

    def get_model_config(self, model_id: str) -> dict:
        """Get base URL, API key, and provider routing for the selected model."""
        from app.core.text_utils import is_local_base_url

        model_id_l = (model_id or "").lower()
        configured_base = self.openai_base_url or "http://100.104.68.115:8081/v1"
        configured_key = self.openai_api_key or "dummy"
        local_default_base = "http://100.104.68.115:8081/v1"

        catalog_entry = next(
            (m for m in self.available_models if (m.get("id") or "").lower() == model_id_l),
            None,
        )
        catalog_provider = catalog_entry.get("provider") if catalog_entry else None
        catalog_base_url = catalog_entry.get("base_url") if catalog_entry else None

        if catalog_provider == "codex" or model_id_l.startswith("gpt-5.3-codex") or "codex" in model_id_l:
            codex_base = configured_base if "chatgpt.com/backend-api" in configured_base else self.codex_default_base_url
            return {"base_url": codex_base, "api_key": self.codex_oauth_access_token or configured_key, "provider": "codex"}

        if catalog_provider == "anthropic" or model_id_l.startswith("claude"):
            return {"base_url": "https://api.anthropic.com", "api_key": self.anthropic_api_key, "provider": "anthropic"}
        if catalog_provider == "google" or model_id_l.startswith("gemini"):
            return {"base_url": "https://generativelanguage.googleapis.com/v1beta", "api_key": self.google_api_key, "provider": "google"}
        if catalog_provider == "local":
            if catalog_base_url:
                local_base = catalog_base_url
            else:
                local_base = configured_base if is_local_base_url(configured_base) else local_default_base
            return {"base_url": local_base, "api_key": configured_key or "dummy", "provider": "local"}
        if catalog_provider == "openai":
            return {"base_url": configured_base, "api_key": configured_key or "dummy", "provider": "openai"}

        # Fallback: global provider
        if self.ai_provider == "codex" or "chatgpt.com/backend-api" in configured_base:
            return {"base_url": configured_base, "api_key": self.codex_oauth_access_token or configured_key, "provider": "codex"}
        if self.ai_provider == "claude":
            return {"base_url": "https://api.anthropic.com", "api_key": self.anthropic_api_key, "provider": "anthropic"}
        if self.ai_provider == "gemini":
            return {"base_url": "https://generativelanguage.googleapis.com/v1beta", "api_key": self.google_api_key, "provider": "google"}
        if is_local_base_url(configured_base):
            return {"base_url": configured_base, "api_key": configured_key or "dummy", "provider": "local"}
        return {"base_url": configured_base, "api_key": configured_key or "dummy", "provider": "openai"}


# Singleton instance
_app_state: Optional[AppState] = None


def get_app_state() -> AppState:
    """Get or create the global app state singleton."""
    global _app_state
    if _app_state is None:
        _app_state = AppState()
    return _app_state
