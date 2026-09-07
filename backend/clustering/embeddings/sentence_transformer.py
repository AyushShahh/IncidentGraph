"""SentenceTransformer local embedding provider implementation."""
import asyncio
from typing import List, Optional
from backend.clustering.embeddings.base import BaseEmbeddingProvider
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class SentenceTransformerEmbeddingProvider(BaseEmbeddingProvider):
    """Local dense embedding provider using sentence-transformers (PyTorch)."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._model = None
        self._dimension: int = 384

    def _get_model(self):
        """Lazy-load the SentenceTransformer model to optimize startup time."""
        if self._model is None:
            logger.info("Loading SentenceTransformer model: %s...", self.model_name)
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self._dimension = self._model.get_sentence_embedding_dimension() or 384
            logger.info("SentenceTransformer model loaded (dim=%d)", self._dimension)
        return self._model

    @property
    def dimension(self) -> int:
        if self._model is None:
            # Standard all-MiniLM-L6-v2 dimension is 384
            return 384
        return self._dimension

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate normalized dense embeddings in a worker thread."""
        if not texts:
            return []

        def _encode():
            model = self._get_model()
            # Generate L2-normalized embeddings for direct cosine similarity
            embeddings = model.encode(
                texts,
                batch_size=32,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            return embeddings.tolist()

        return await asyncio.to_thread(_encode)
