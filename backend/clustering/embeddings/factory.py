"""Embedding provider factory supporting pluggable backends."""
from typing import Optional, Dict
from backend.clustering.embeddings.base import BaseEmbeddingProvider
from backend.clustering.embeddings.sentence_transformer import SentenceTransformerEmbeddingProvider
from backend.clustering.embeddings.ollama import OllamaEmbeddingProvider
from backend.clustering.embeddings.gemini import GeminiEmbeddingProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_providers: Dict[str, BaseEmbeddingProvider] = {}


def get_embedding_provider(provider_type: Optional[str] = None) -> BaseEmbeddingProvider:
    """Retrieve or instantiate a cached embedding provider according to configuration."""
    provider_name = (provider_type or settings.EMBEDDING_PROVIDER).strip().lower()

    if provider_name in _providers:
        return _providers[provider_name]

    logger.info("Initializing embedding provider: '%s'", provider_name)

    if provider_name in ("sentence-transformers", "sentence_transformers", "local"):
        provider = SentenceTransformerEmbeddingProvider(model_name=settings.EMBEDDING_MODEL)
    elif provider_name == "ollama":
        provider = OllamaEmbeddingProvider(
            base_url=settings.OLLAMA_BASE_URL,
            model_name=settings.OLLAMA_EMBEDDING_MODEL,
        )
    elif provider_name in ("gemini", "google"):
        provider = GeminiEmbeddingProvider(
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.GEMINI_EMBEDDING_MODEL,
        )
    else:
        logger.warning(
            "Unknown embedding provider '%s', falling back to SentenceTransformer",
            provider_name,
        )
        provider = SentenceTransformerEmbeddingProvider(model_name=settings.EMBEDDING_MODEL)

    _providers[provider_name] = provider
    return provider
