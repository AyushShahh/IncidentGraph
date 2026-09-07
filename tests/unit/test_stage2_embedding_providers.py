"""Unit tests for pluggable embedding providers and factory."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.clustering.embeddings.base import BaseEmbeddingProvider
from backend.clustering.embeddings.factory import get_embedding_provider
from backend.clustering.embeddings.ollama import OllamaEmbeddingProvider
from backend.clustering.embeddings.gemini import GeminiEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    @property
    def dimension(self) -> int:
        return 4

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_base_embedding_provider_embed_text():
    provider = MockEmbeddingProvider()
    assert provider.dimension == 4
    vec = await provider.embed_text("test sentence")
    assert vec == [1.0, 0.0, 0.0, 0.0]


def test_factory_returns_sentence_transformer_by_default():
    provider = get_embedding_provider("sentence-transformers")
    assert provider is not None
    assert provider.dimension == 384


def test_factory_returns_ollama():
    provider = get_embedding_provider("ollama")
    assert isinstance(provider, OllamaEmbeddingProvider)
    assert provider.base_url == "http://host.docker.internal:11434"


def test_factory_returns_gemini():
    provider = get_embedding_provider("gemini")
    assert isinstance(provider, GeminiEmbeddingProvider)


@pytest.mark.asyncio
async def test_ollama_embed_batch_mock():
    provider = OllamaEmbeddingProvider(base_url="http://localhost:11434", model_name="nomic-embed-text")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "embeddings": [
            [0.5, 0.5, 0.5, 0.5],
            [1.0, 0.0, 0.0, 0.0],
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        results = await provider.embed_batch(["hello", "world"])
        assert len(results) == 2
        assert len(results[0]) == 4
        # Verify L2 normalization
        import math
        norm = math.sqrt(sum(x * x for x in results[0]))
        assert abs(norm - 1.0) < 1e-4
