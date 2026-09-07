"""Embeddings package exposing base interface, concrete providers, and factory."""
from backend.clustering.embeddings.base import BaseEmbeddingProvider
from backend.clustering.embeddings.sentence_transformer import SentenceTransformerEmbeddingProvider
from backend.clustering.embeddings.ollama import OllamaEmbeddingProvider
from backend.clustering.embeddings.gemini import GeminiEmbeddingProvider
from backend.clustering.embeddings.factory import get_embedding_provider

__all__ = [
    "BaseEmbeddingProvider",
    "SentenceTransformerEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "GeminiEmbeddingProvider",
    "get_embedding_provider",
]
