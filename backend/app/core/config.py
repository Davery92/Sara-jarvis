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
    ai_provider: str = "local"  # Options: local, gemini, openai, claude, custom
    openai_base_url: str = "http://100.104.68.115:11434/v1"
    openai_model: str = "gpt-oss:120b"
    openai_api_key: str = "dummy"
    anthropic_api_key: str = ""  # Separate key for Anthropic Claude API
    gemini_api_key: str = ""  # Separate key for Google Gemini API
    embedding_base_url: str = "http://10.185.1.8:11434"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    # LLM Failover Configuration
    llm_primary_url: str = "http://100.104.68.115:11434/v1"
    llm_fallback_url: str = "http://10.185.1.8:11434/v1"
    llm_request_timeout: float = 8.0  # Short timeout for failover detection
    llm_health_check_interval: int = 30  # seconds between health checks
    llm_health_check_timeout: float = 5.0  # timeout for health check requests
    llm_recovery_checks_required: int = 3  # successful checks to mark as healthy
    
    # Search / Reranker / Caching
    search_provider: str = "tavily"  # Options: searxng, tavily
    tavily_api_key: str = "REDACTED_TAVILY_KEY"
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
    
    # Security
    jwt_secret: str = "sara-hub-jwt-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24 * 7  # 1 week
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
    
    # Database
    database_url: str = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
    
    # Storage
    minio_url: str = "http://minio:9000"
    minio_bucket: str = "sara-docs"
    minio_access_key: str = "sara"
    minio_secret_key: str = "sara1234"
    
    # Scheduling
    timezone: str = "America/New_York"

    # Home Assistant
    ha_host: str = "10.185.1.61"
    ha_port: int = 8123
    ha_token: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODhkZGQ0ZWVlOWI0ODNjOTIwMTU1YTA0ZTM3YTk0NCIsImlhdCI6MTc2NTU2OTczNiwiZXhwIjoyMDgwOTI5NzM2fQ.oLO_hR-RzJFP-TsrKWEteDZbUReVEUdtENIeMAE5Teg"
    
    # Memory settings
    memory_chunk_size: int = 700
    memory_chunk_overlap: int = 150
    memory_search_limit: int = 12
    memory_age_months: int = 12
    memory_compaction_daily_hour: int = 2  # 2 AM
    memory_compaction_daily_minute: int = 10
    memory_compaction_weekly_day: int = 6  # Sunday
    memory_compaction_weekly_hour: int = 3  # 3 AM
    
    class Config:
        env_file = ".env"


settings = Settings()
