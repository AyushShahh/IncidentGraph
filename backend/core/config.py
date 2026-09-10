"""Centralized application configuration using Pydantic Settings."""
from functools import lru_cache
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App & Runtime Environment
    PROJECT_NAME: str = "AI Incident Intelligence Platform"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    DEPLOYMENT_VERSION: str = "v1.0.0"

    # API Server Settings
    API_V1_STR: str = "/api/v1"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    BACKEND_PORT: int = 8000

    # PostgreSQL Database Configuration
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "incident_db"
    DATABASE_URL: Optional[str] = None

    @model_validator(mode="after")
    def assemble_database_url(self) -> "Settings":
        """Build DATABASE_URL dynamically from components if not provided directly."""
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        return self

    # Redis Cache & Broker Configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_URL: str = "redis://localhost:6379/0"

    # Apache Kafka Configuration
    KAFKA_HOST: str = "localhost"
    KAFKA_PORT: int = 9092
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_LOGS_TOPIC: str = "service-logs"
    KAFKA_INCIDENTS_TOPIC: str = "incident-events"
    KAFKA_CONSUMER_GROUP: str = "incident-processor-group"

    # Qdrant Vector DB Configuration
    QDRANT_HOST: str = "localhost"
    QDRANT_HTTP_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_URL: Optional[str] = None
    QDRANT_API_KEY: Optional[str] = None

    # Celery & Background Worker Settings
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_WORKER_CONCURRENCY: int = 1

    # Stage 2: Batch Ingestion, Clustering & Consumer Settings
    KAFKA_BATCH_SIZE: int = 500
    KAFKA_BATCH_INTERVAL_SECONDS: float = 10.0
    MONITORED_LOG_LEVELS: str = "ERROR,WARNING"

    # Stage 2: Deduplication & Similarity Settings
    SIMILARITY_THRESHOLD: float = 0.85
    REDIS_FINGERPRINT_TTL_SECONDS: int = 172800  # 2 days

    # Stage 2: Pluggable Embeddings Settings
    EMBEDDING_PROVIDER: str = "sentence-transformers"  # "sentence-transformers", "gemini", "ollama"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_EMBEDDING_MODEL: str = "models/text-embedding-004"
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"

    # Stage 2: HDBSCAN Clustering Settings
    HDBSCAN_MIN_CLUSTER_SIZE: int = 2
    HDBSCAN_MIN_SAMPLES: int = 1
    HDBSCAN_CLUSTER_SELECTION_EPSILON: float = 0.0
    HDBSCAN_MAX_CLUSTER_DISTANCE: float = 0.85

    # Stage 3: Repository Intelligence & Context Engine Settings
    REPOSITORIES_ROOT_DIR: str = "services"
    MANIFESTS_STORAGE_DIR: str = "backend/data/manifests"
    STAGE3_CODE_CHUNK_LINES: int = 80
    STAGE3_MAX_CONTEXT_TOKENS: int = 3500

    # Stage 4: Pluggable LLM Providers & API Keys
    LLM_PROVIDER: str = "openai"  # "openai", "anthropic", "gemini", "groq", "ollama", "vllm", "llamacpp", "mock"
    LLM_MODEL: str = "gpt-4o-mini"

    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com/v1"

    GEMINI_LLM_MODEL: str = "gemini-1.5-pro"
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"

    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    OLLAMA_LLM_MODEL: str = "qwen2.5-coder:latest"

    VLLM_BASE_URL: str = "http://localhost:8000/v1"
    VLLM_MODEL: str = "meta-llama/Llama-3.1-8B-Instruct"

    LLAMACPP_BASE_URL: str = "http://localhost:8080/v1"
    LLAMACPP_MODEL: str = "default"

    # Stage 4: Investigation Loop & Token Limits
    STAGE4_MAX_ITERATIONS: int = 5
    STAGE4_CONFIDENCE_THRESHOLD: float = 0.85
    STAGE4_TOKEN_BUDGET: int = 4000
    STAGE4_TOOL_TIMEOUT_SECONDS: float = 10.0
    STAGE4_MEMORY_SIMILARITY_THRESHOLD: float = 0.80
    STAGE4_EXECUTION_MEMORY_TTL_SECONDS: int = 86400  # 24 hours

    @property
    def monitored_log_levels_set(self) -> set[str]:
        return {lvl.strip().upper() for lvl in self.MONITORED_LOG_LEVELS.split(",") if lvl.strip()}

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton provider."""
    return Settings()


settings = get_settings()
