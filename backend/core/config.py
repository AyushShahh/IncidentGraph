"""Centralized application configuration using Pydantic Settings."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "AI Incident Intelligence Platform"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # API
    API_V1_STR: str = "/api/v1"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # PostgreSQL Database
    DATABASE_URL: str = "postgresql+asyncpg://ayush:ayushshah@localhost:5432/incident_db"

    # Redis Cache & Broker
    REDIS_URL: str = "redis://localhost:6379/0"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_LOGS_TOPIC: str = "service-logs"
    KAFKA_INCIDENTS_TOPIC: str = "incident-events"
    KAFKA_CONSUMER_GROUP: str = "incident-processor-group"

    # Qdrant Vector DB
    QDRANT_HOST: str = "localhost"
    QDRANT_HTTP_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_API_KEY: str | None = None

    # LLM & Embedding Models
    LLM_MODEL: str = "gpt-4o"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    OPENAI_API_KEY: str | None = None

    # Celery & Queue Settings
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_WORKER_CONCURRENCY: int = 1

    # Stage 2: Batch Clustering & Consumer Settings
    KAFKA_BATCH_SIZE: int = 500
    KAFKA_BATCH_INTERVAL_SECONDS: float = 10.0
    MONITORED_LOG_LEVELS: str = "ERROR,WARNING"

    # Stage 2: Deduplication & Similarity Settings
    SIMILARITY_THRESHOLD: float = 0.85
    REDIS_FINGERPRINT_TTL_SECONDS: int = 172800  # 2 days

    # Stage 2: Pluggable Embeddings Settings
    EMBEDDING_PROVIDER: str = "sentence-transformers"  # "sentence-transformers", "gemini", "ollama"
    GEMINI_API_KEY: str | None = None
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

    @property
    def monitored_log_levels_set(self) -> set[str]:
        return {lvl.strip().upper() for lvl in self.MONITORED_LOG_LEVELS.split(",") if lvl.strip()}

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton provider."""
    # TODO: Add dynamic validation rules and secret management in production
    return Settings()


settings = get_settings()
