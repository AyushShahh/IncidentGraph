"""Google Gemini embedding provider implementation."""
import math
from typing import List, Optional
import httpx

from backend.clustering.embeddings.base import BaseEmbeddingProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Embedding provider using Google Gemini Embeddings API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_EMBEDDING_MODEL
        self.timeout = timeout
        self._dimension: int = 768

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
        """Batch embedding request to Google Generative Language API."""
        if not texts:
            return []

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured for GeminiEmbeddingProvider")

        url = f"https://generativelanguage.googleapis.com/v1beta/{self.model_name}:batchEmbedContents?key={self.api_key}"

        requests = [
            {"model": self.model_name, "content": {"parts": [{"text": t}]}}
            for t in texts
        ]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json={"requests": requests})
            resp.raise_for_status()
            data = resp.json()
            raw_embeddings = [item["values"] for item in data.get("embeddings", [])]
            if raw_embeddings:
                self._dimension = len(raw_embeddings[0])
                return [self._normalize_vector(v) for v in raw_embeddings]
            return []
