from pydantic_settings import BaseSettings
from typing import List, Optional, Dict, Any
from pydantic import field_validator
import json
import os


class Settings(BaseSettings):
    # Sara Branding
    assistant_name: str = "Sara"
    domain: str = "sara.avery.cloud"
    frontend_url: str = "https://sara.avery.cloud"
    backend_url: str = "https://sara.avery.cloud/api"
    
    # LLM Configuration
    openai_base_url: str = "http://100.104.68.115:11434/v1"
    openai_model: str = "gpt-oss:120b"
    # Optional secondary model for notifications/light tasks
    openai_notification_model: Optional[str] = None
    openai_api_key: str = "dummy"
    embedding_base_url: str = "http://100.104.68.115:11434"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    
    # Search / Reranker / Caching
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
    cookie_domain: Optional[str] = None  # None allows all domains for development
    cookie_secure: bool = False  # False for HTTP development
    cookie_samesite: str = "lax"
    cors_origins: List[str] = ["https://sara.avery.cloud", "http://10.185.1.188:3000", "http://localhost:3000"]
    
    # Database
    database_url: str = "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
    
    # Storage
    minio_url: str = "http://minio:9000"
    minio_bucket: str = "sara-docs"
    minio_access_key: str = "sara"
    minio_secret_key: str = "sara123"
    
    # Scheduling
    timezone: str = "America/New_York"
    
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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: Any) -> Any:
        """Allow CORS_ORIGINS to be provided as JSON array or comma-separated string."""
        if isinstance(v, str):
            sv = v.strip()
            if not sv:
                return []
            if sv.startswith("["):
                try:
                    parsed = json.loads(sv)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
            # Fallback: comma-separated
            return [s.strip() for s in sv.split(",") if s.strip()]
        return v


settings = Settings()
