"""Abstract base interface for pluggable embedding providers."""
from abc import ABC, abstractmethod
from typing import List


class BaseEmbeddingProvider(ABC):
    """Abstract interface defining the contract for dense text embedding providers."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality produced by the embedding model."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Compute dense vector embeddings for a batch of strings.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of float lists representing dense embedding vectors.
        """
        pass

    async def embed_text(self, text: str) -> List[float]:
        """Compute embedding for a single text string."""
        results = await self.embed_batch([text])
        if not results:
            raise RuntimeError("Embedding provider returned empty result")
        return results[0]
