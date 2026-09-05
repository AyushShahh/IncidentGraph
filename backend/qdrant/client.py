"""Qdrant client singleton and collection initialization."""
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import Distance, VectorParams
from backend.core.config import settings
from backend.core.logging import get_logger
from shared.constants import QDRANT_INCIDENT_COLLECTION, QDRANT_CODE_COLLECTION

logger = get_logger(__name__)

_qdrant_client: AsyncQdrantClient | None = None


async def get_qdrant_client() -> AsyncQdrantClient:
    """Obtain or initialize AsyncQdrantClient."""
    global _qdrant_client
    if _qdrant_client is None:
        logger.info(
            "Connecting to Qdrant at %s:%s",
            settings.QDRANT_HOST,
            settings.QDRANT_HTTP_PORT,
        )
        _qdrant_client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_HTTP_PORT,
            api_key=settings.QDRANT_API_KEY,
        )
    return _qdrant_client


async def init_collections(vector_dim: int = 384) -> None:
    """Initialize necessary collections if they don't already exist."""
    # TODO: Make vector dimension dynamic based on the active embedding model
    client = await get_qdrant_client()
    for col in [QDRANT_INCIDENT_COLLECTION, QDRANT_CODE_COLLECTION]:
        exists = await client.collection_exists(col)
        if not exists:
            logger.info("Creating Qdrant collection: %s (dim=%d)", col, vector_dim)
            await client.create_collection(
                collection_name=col,
                vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE),
            )
