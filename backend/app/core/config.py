from pydantic_settings import BaseSettings
from typing import List, Optional, Dict
import os


class Settings(BaseSettings):
    # Sara Branding
    assistant_name: str = "Sara"
    domain: str = "sara.avery.cloud"
    frontend_url: str = "https://sara.avery.cloud"
    backend_url: str = "https://sara.avery.cloud/api"

    # LLM Configuration
    ai_provider: str = "local"  # Options: local, gemini, openai, claude, codex, custom
    openai_base_url: str = "http://100.104.68.115:11434/v1"
    openai_model: str = "gpt-oss:20b"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    embedding_base_url: str = "http://10.185.1.8:11434"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    # LLM Failover Configuration
    llm_primary_url: str = "http://100.104.68.115:11434/v1"
    llm_fallback_url: str = "http://10.185.1.8:11434/v1"
    llm_fallback_model: str = "gpt-oss:latest"  # Model available on fallback endpoint
    llm_request_timeout: float = 60.0  # Timeout for LLM requests (120B model needs time)
    llm_health_check_interval: int = 30  # seconds between health checks
    llm_health_check_timeout: float = 5.0  # timeout for health check requests
    llm_recovery_checks_required: int = 3  # successful checks to mark as healthy

    # Background LLM Configuration (separate from chat - always uses local models)
    bg_llm_primary_url: str = "http://100.104.68.115:11434/v1"
    bg_llm_primary_model: str = "gpt-oss:120b-32k"
    bg_llm_fallback_url: str = "http://10.185.1.8:11434/v1"
    bg_llm_fallback_model: str = "gpt-oss:20b"
    bg_llm_request_timeout: float = 180.0
    bg_llm_connect_timeout: float = 6.0
    bg_llm_num_ctx: int = 32768
    learning_guide_num_ctx: int = 32768
    learning_lesson_num_ctx: int = 49152
    learning_lesson_request_timeout: float = 300.0

    # Search / Reranker / Caching
    search_provider: str = "tavily"  # Options: searxng, tavily
    tavily_api_key: str = ""
    searxng_base_url: str = "http://10.185.1.8:4000"
    searxng_timeout_s: float = 3.0
    searxng_language: str = "en"
    search_cache_ttl_s: int = 1800  # 30 minutes
    page_cache_ttl_s: int = 172800  # 48 hours
    redis_url: str = "redis://localhost:6379/0"
    # If not provided, fallback to embedding_base_url in service
    reranker_base_url: Optional[str] = None
    reranker_model: str = "bge-reranker-v2-m3:latest"

    # Domain policy
    domain_boosts: Dict[str, float] = {}
    domain_denylist: List[str] = []

    # Security — secrets loaded from .env, no hardcoded defaults
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24 * 7  # 1 week
    # Comma-separated admin email allowlist for automation admin APIs
    automation_admin_emails: str = ""
    cookie_domain: str = ".sara.avery.cloud"
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    cors_origins: List[str] = [
        "https://sara.avery.cloud",
        "http://sara.avery.cloud",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://10.185.1.180:3000",
        "http://10.185.1.188:3000",
        "http://10.185.1.180",
        "http://10.185.1.188",
    ]

    # Database — loaded from .env
    database_url: str = ""

    # Storage
    minio_url: str = "http://minio:9000"
    minio_bucket: str = "sara-docs"
    minio_access_key: str = "sara"
    minio_secret_key: str = ""

    # Scheduling
    timezone: str = "America/New_York"

    # Home Assistant — token loaded from .env
    ha_host: str = "10.185.1.61"
    ha_port: int = 8123
    ha_token: str = ""

    # Memory settings
    memory_chunk_size: int = 700
    memory_chunk_overlap: int = 150
    memory_search_limit: int = 12
    memory_age_months: int = 12
    memory_compaction_daily_hour: int = 2  # 2 AM
    memory_compaction_daily_minute: int = 10
    memory_compaction_weekly_day: int = 6  # Sunday
    memory_compaction_weekly_hour: int = 3  # 3 AM

    # Microsoft Graph Email Integration — secrets loaded from .env
    msgraph_client_id: str = ""
    msgraph_client_secret: str = ""
    msgraph_tenant_id: str = ""
    msgraph_mailboxes: List[str] = ["davery@riskninja.ai", "devadmin@riskninja.ai"]
    email_sync_interval_minutes: int = 3

    # Sentry Error Tracking
    sentry_dsn: str = ""
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.1

    # Skills System Configuration
    skills_enabled: bool = True
    skills_dirs: List[str] = ["backend/skills"]
    skills_hot_reload: bool = True

    # Autonomy Evolution Feature Flags (Cortana Evolution)
    autonomy_traces_enabled: bool = True         # Phase 0: action tracing
    autonomy_structured_plan: bool = False        # Phase 1: 6-phase cycle with structured plan
    autonomy_policy_engine: bool = False          # Phase 1: policy gating on tool execution
    autonomy_attention_enabled: bool = False       # Phase 2: attention queue for deferred items
    autonomy_missions_enabled: bool = True         # Phase 2: mission engine
    autonomy_policy_candidates_enabled: bool = False  # Phase 3: dream→policy candidates
    temerant_enabled: bool = True  # Temerant RPG surface rollout flag
    temerant_oracle_enabled: bool = True  # Enables oracle roll/event mechanics
    temerant_narrative_enabled: bool = True  # Enables narrative/journal generation features
    temerant_auto_ingestion_enabled: bool = False  # Enables passive ingestion from habits/learning/fitness
    temerant_rpg_enabled: bool = True  # Enables separate scene-based Temerant RPG
    temerant_rpg_narrative_enabled: bool = True  # Enables narrative generation for separate RPG
    temerant_rpg_model: str = "gpt-oss:120b-32k"  # Dedicated GM model for scene-based RPG
    temerant_rpg_num_ctx: int = 32768  # Dedicated context window for scene-based RPG narration

    # Autonomy rollout thresholds (used by /autonomy/rollout/summary evaluation)
    autonomy_rollout_min_runs_for_eval: int = 10
    autonomy_rollout_max_fallback_rate: float = 0.25
    autonomy_rollout_max_action_failure_rate: float = 0.10
    autonomy_rollout_max_dedup_block_rate: float = 0.45
    autonomy_rollout_max_attention_backlog_ratio: float = 0.70
    autonomy_rollout_max_mission_failure_rate: float = 0.20
    autonomy_rollout_max_mission_nonterminal_ratio: float = 0.70

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
