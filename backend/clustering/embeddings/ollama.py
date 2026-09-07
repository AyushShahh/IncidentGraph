"""Ollama embedding provider for local or remote Ollama server instances."""
import math
from typing import List, Optional
import httpx

from backend.clustering.embeddings.base import BaseEmbeddingProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """Dense embedding provider interacting with an Ollama HTTP service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model_name = model_name or settings.OLLAMA_EMBEDDING_MODEL
        self.timeout = timeout
        self._dimension: int = 384  # Default fallback

    @property
    def dimension(self) -> int:
        return self._dimension

    @staticmethod
    def _normalize_vector(vec: List[float]) -> List[float]:
        """L2-normalize an embedding vector."""
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 1e-12:
            return [x / norm for x in vec]
        return vec

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Fetch embeddings for batch of texts from Ollama API."""
        if not texts:
            return []

        embeddings: List[List[float]] = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # First attempt modern Ollama /api/embed batch endpoint
            try:
                embed_url = f"{self.base_url}/api/embed"
                response = await client.post(
                    embed_url,
                    json={"model": self.model_name, "input": texts},
                )
                if response.status_code == 200:
                    data = response.json()
                    raw_embeddings = data.get("embeddings", [])
                    if raw_embeddings:
                        self._dimension = len(raw_embeddings[0])
                        return [self._normalize_vector(vec) for vec in raw_embeddings]
            except Exception as exc:
                logger.warning("Ollama /api/embed batch call failed (%s), falling back to /api/embeddings", exc)

            # Fallback: sequential /api/embeddings endpoint
            embeddings_url = f"{self.base_url}/api/embeddings"
            for text in texts:
                resp = await client.post(
                    embeddings_url,
                    json={"model": self.model_name, "prompt": text},
                )
                resp.raise_for_status()
                vec = resp.json().get("embedding", [])
                if vec:
                    self._dimension = len(vec)
                    embeddings.append(self._normalize_vector(vec))
                else:
                    embeddings.append([0.0] * self._dimension)

        return embeddings
