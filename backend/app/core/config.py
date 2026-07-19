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
    openai_base_url: str = "http://100.104.68.115:8081/v1"
    openai_model: str = "qwen3.6-27b"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    embedding_base_url: str = "http://embeddings:8100"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    # LLM Failover Configuration
    llm_primary_url: str = "http://100.104.68.115:8081/v1"
    llm_fallback_url: str = "http://100.104.68.115:8081/v1"
    llm_fallback_model: str = "qwen3.6-27b"
    llm_request_timeout: float = 60.0  # Timeout for LLM requests (120B model needs time)
    llm_health_check_interval: int = 30  # seconds between health checks
    llm_health_check_timeout: float = 5.0  # timeout for health check requests
    llm_recovery_checks_required: int = 3  # successful checks to mark as healthy

    # Background LLM Configuration (separate from chat - always uses local models)
    bg_llm_primary_url: str = "http://100.104.68.115:8081/v1"
    bg_llm_primary_model: str = "qwen3.6-27b"
    bg_llm_fallback_url: str = "http://100.104.68.115:8081/v1"
    bg_llm_fallback_model: str = "qwen3.6-27b"
    bg_llm_request_timeout: float = 600.0  # 10min — 27B reasoning model on ~10k-token ACS payloads needs the headroom
    bg_llm_connect_timeout: float = 6.0
    bg_llm_num_ctx: int = 32768
    bg_llm_fallback_max_tokens: int = 24000  # Max input tokens for fallback model (leave headroom from 32k window)

    # Phase 4 — run agent dispatch in the Celery `dispatch` worker (durable across
    # backend restarts) instead of in-process asyncio. Falls back to in-process if
    # the enqueue fails.
    dispatch_via_celery: bool = True
    # Progress-based watchdog: kill a dispatch task only after this many seconds
    # with NO progress event (replaces the fixed 4h auto-expire).
    dispatch_stall_seconds: int = 900  # 15 min of no progress
    learning_guide_num_ctx: int = 32768

    # Research Executor LLM Configuration
    # Default: shares the BG LLM endpoint (whatever is currently loaded on it).
    # The actual model name is discovered via /v1/models at plan-create time, so
    # `research_llm_model` here is only a fallback if discovery fails.
    research_llm_url: str = "http://100.104.68.115:8081/v1"
    research_llm_model: str = "qwen3.6-27b"
    research_llm_timeout: float = 300.0
    research_llm_max_tokens: int = 4096
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
    # Autonomy rollout thresholds (used by /autonomy/rollout/summary evaluation)
    autonomy_rollout_min_runs_for_eval: int = 10
    autonomy_rollout_max_fallback_rate: float = 0.25
    autonomy_rollout_max_action_failure_rate: float = 0.10
    autonomy_rollout_max_dedup_block_rate: float = 0.45
    autonomy_rollout_max_attention_backlog_ratio: float = 0.70
    autonomy_rollout_max_mission_failure_rate: float = 0.20
    autonomy_rollout_max_mission_nonterminal_ratio: float = 0.70

    # Proxmox Dynamic Container Provisioning
    proxmox_api_url: str = "https://10.185.1.203:8006/api2/json"
    proxmox_node: str = "sara-node"
    proxmox_token_id: str = "sara@pve!api-token"
    proxmox_token_secret: str = ""  # from .env: PROXMOX_TOKEN_SECRET
    proxmox_verify_ssl: bool = False
    proxmox_ssh_public_key_path: str = "~/.ssh/sara_agent.pub"
    proxmox_vmid_range_start: int = 200
    proxmox_vmid_range_end: int = 299
    proxmox_max_containers: int = 4
    proxmox_max_cores: int = 8
    proxmox_max_memory_mb: int = 16384
    proxmox_default_storage: str = "local-lvm"

    # ACS v2 — in-VM cognition daemon. Shared bearer secret between backend and daemon.
    acs_daemon_token: str = ""  # from .env: ACS_DAEMON_TOKEN
    # The single user Sara is owned by; she notifies them via /api/acs/v2/notify.
    acs_owner_user_id: str = "64f37c56-85cb-4590-8de9-adfc17d343ed"  # from .env: ACS_OWNER_USER_ID
    # Default folder for notes Sara writes via the daemon (write_note tool).
    # Falls back to no-folder if unset or the folder no longer exists.
    acs_default_note_folder_id: str = "36ca18ea-7b4b-4b48-ac60-95e1b720ec57"  # "Sara's Notes"
    # Sandbox runner for user-defined tools (acs_user_tools.invoke). Empty
    # means /invoke records the call but returns 503 — the API contract is
    # sealed so the daemon can develop the rest of the loop while the
    # sidecar is being built/deployed.
    acs_tool_runner_url: str = ""  # from .env: ACS_TOOL_RUNNER_URL

    # GPU compute host — accessible from containers for training/inference
    gpu_host: str = "10.185.1.8"
    gpu_host_user: str = "david"
    gpu_host_ssh_key: str = "~/.ssh/sara_agent"
    gpu_host_llm_url: str = "http://10.185.1.8:8686/v1"
    gpu_host_llm_model: str = "Qwen3.5-35B-A3B"

    # ACS v2 Feature Flags
    # Setting this False reverts ACS to the v1 flat curiosity queue path,
    # which is untested in this deployment. v2 is the live path; leave True.
    acs_v2_enabled: bool = True                     # Master toggle for all v2 features
    acs_v2_max_session_minutes: int = 360           # Hard ceiling (6 hours)
    acs_v2_min_session_minutes: int = 15            # Hard floor
    acs_v2_low_engagement_threshold: float = 0.3
    acs_v2_low_engagement_streak: int = 3           # Consecutive low turns before early end
    acs_v2_decay_half_life_days: int = 14           # Fascination half-life (was 7 — collapsed working graph to 8 active nodes)
    acs_v2_similarity_dedup_threshold: float = 0.85 # Cosine threshold for node dedup
    acs_v2_bridge_threshold: float = 0.78           # Cosine threshold for bridge opportunities
    acs_v2_max_context_nodes: int = 15              # Max interest nodes in prompt context
    acs_v2_mode_max_repeat: int = 2                 # Don't pick same mode 2x in a row
    acs_execution_ratio: float = 0.7              # Fraction of sessions dedicated to plan execution vs free

    # Code Mode (chat /code) — coding agent on the sara VM
    github_pat: str = ""                              # fine-grained PAT: Contents R/W + Metadata R
    git_author_name: str = "Sara"                     # commit author name
    git_author_email: str = "sara@avery.cloud"        # commit author email
    code_mode_root: str = "~/code-projects"           # base dir on the VM for bare clones + worktrees
    code_mode_default_repo: str = "Davery92/sara-sandbox"  # used when `/code <task>` is sent with no active session
    code_mode_llm_url: str = ""                        # optional LLM endpoint override; empty = use bg llm
    code_mode_max_rounds: int = 60                    # max tool-call rounds per turn

    # Sara Fleet — health agents + read-only diagnostics (FLEET_DESIGN.md)
    fleet_enroll_secret: str = ""                     # from .env: shared secret to enroll a new agent
    fleet_report_interval: int = 300                  # default agent report cadence (seconds)
    fleet_public_url: str = "https://sara-api.avery.cloud"  # API domain the installer/agent points at (NOT the SPA host)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
