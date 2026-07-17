from pydantic_settings import BaseSettings
from typing import List
import os


class LocalSettings(BaseSettings):
    # Sara Branding
    assistant_name: str = "Sara"
    domain: str = "sara.avery.cloud"
    frontend_url: str = "https://sara.avery.cloud"
    backend_url: str = "https://sara.avery.cloud/api"
    
    # LLM Configuration
    ai_provider: str = "local"  # Options: local, gemini, openai, custom
    openai_base_url: str = "http://100.104.68.115:8081/v1"
    openai_model: str = "qwen3.6-27b"
    openai_api_key: str = "dummy"
    embedding_base_url: str = "http://embeddings:8100"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    
    # Security
    jwt_secret: str = "sara-hub-jwt-secret-development"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24 * 7  # 1 week
    cookie_domain: str = ".sara.avery.cloud"
    cookie_secure: bool = False  # Development mode
    cookie_samesite: str = "lax"
    cors_origins: List[str] = ["https://sara.avery.cloud", "http://localhost:3000", "http://10.185.1.180:3000"]
    
    # Database - IMPORTANT: Always use PostgreSQL, never SQLite
    database_url: str = "postgresql+psycopg://sara:sara123@db:5432/sara_hub"
    
    # Storage - Local file system
    minio_url: str = "file://./uploads"
    minio_bucket: str = "sara-docs"
    minio_access_key: str = "dummy"
    minio_secret_key: str = "dummy"
    
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
        extra = "ignore"


# Use local settings for development
settings = LocalSettings()
