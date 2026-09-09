"""Vector indexing and semantic code search engine backed by Qdrant.

Indexes code, documentation, and configuration chunks into the `repository_code`
collection for semantic retrieval and similarity search.
"""
from typing import Any, Dict, List, Optional, Tuple
import uuid
from qdrant_client.http.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
)

from backend.clustering.embeddings.factory import get_embedding_provider
from backend.core.logging import get_logger
from backend.qdrant.client import get_qdrant_client
from backend.repository.schemas import ChunkType, CodeChunk
from shared.constants import QDRANT_CODE_COLLECTION

logger = get_logger(__name__)


class VectorIndexer:
    """Manages embedding generation, vector upsert, and semantic code search in Qdrant."""

    def __init__(self, collection_name: str = QDRANT_CODE_COLLECTION) -> None:
        self.collection_name = collection_name
        self._provider = None

    def _get_provider(self):
        if self._provider is None:
            self._provider = get_embedding_provider()
        return self._provider

    @staticmethod
    def generate_chunk_uuid(service_name: str, file_path: str, start_line: int) -> str:
        """Deterministically derive a UUID5 string from chunk coordinates."""
        unique_key = f"{service_name}:{file_path}:{start_line}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, unique_key))

    async def upsert_chunks(self, chunks: List[CodeChunk], batch_size: int = 50) -> int:
        """Generate embeddings and upsert code/doc chunks into Qdrant.

        Returns:
            Number of chunks successfully indexed.
        """
        if not chunks:
            return 0

        provider = self._get_provider()
        client = await get_qdrant_client()
        total_upserted = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.content for c in batch]

            try:
                embeddings = await provider.embed_batch(texts)
            except Exception as exc:
                logger.error("Failed to compute embeddings for batch: %s", exc)
                continue

            points: List[PointStruct] = []
            for chunk, emb in zip(batch, embeddings):
                point_id = self.generate_chunk_uuid(
                    chunk.service_name, chunk.file_path, chunk.start_line
                )
                payload: Dict[str, Any] = {
                    "chunk_id": chunk.chunk_id,
                    "service_name": chunk.service_name,
                    "file_path": chunk.file_path,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "chunk_type": chunk.chunk_type.value,
                    "content": chunk.content,
                    "symbol_names": chunk.symbol_names,
                    "token_estimate": chunk.token_estimate,
                }
                points.append(
                    PointStruct(
                        id=point_id,
                        vector=emb,
                        payload=payload,
                    )
                )

            try:
                await client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                )
                total_upserted += len(points)
            except Exception as exc:
                logger.error("Failed to upsert points to Qdrant collection '%s': %s", self.collection_name, exc)

        logger.info("Successfully indexed %d/%d chunks in Qdrant.", total_upserted, len(chunks))
        return total_upserted

    async def search_code(
        self,
        query: str,
        service: Optional[str] = None,
        chunk_type: Optional[ChunkType] = None,
        limit: int = 5,
        score_threshold: float = 0.40,
    ) -> List[Tuple[CodeChunk, float]]:
        """Perform semantic search across indexed repository code and docs.

        Returns:
            List of tuples (CodeChunk, cosine_similarity_score).
        """
        provider = self._get_provider()
        client = await get_qdrant_client()

        try:
            query_vector = await provider.embed_text(query)
        except Exception as exc:
            logger.error("Failed embedding search query '%s': %s", query, exc)
            return []

        # Construct filters
        must_conditions = []
        if service:
            must_conditions.append(
                FieldCondition(key="service_name", match=MatchValue(value=service.lower()))
            )
        if chunk_type:
            must_conditions.append(
                FieldCondition(key="chunk_type", match=MatchValue(value=chunk_type.value))
            )

        query_filter = Filter(must=must_conditions) if must_conditions else None

        results = []
        try:
            if hasattr(client, "query_points"):
                res = await client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    score_threshold=score_threshold,
                )
                hits = res.points if hasattr(res, "points") else res
            elif hasattr(client, "search_points"):
                hits = await client.search_points(
                    collection_name=self.collection_name,
                    vector=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    score_threshold=score_threshold,
                )
            elif hasattr(client, "search"):
                hits = await client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    score_threshold=score_threshold,
                )
            else:
                hits = []

            for hit in hits:
                payload = hit.payload or {}
                chunk = CodeChunk(
                    chunk_id=payload.get("chunk_id", ""),
                    service_name=payload.get("service_name", ""),
                    file_path=payload.get("file_path", ""),
                    start_line=payload.get("start_line", 1),
                    end_line=payload.get("end_line", 1),
                    chunk_type=ChunkType(payload.get("chunk_type", "code")),
                    content=payload.get("content", ""),
                    symbol_names=payload.get("symbol_names", []),
                    token_estimate=payload.get("token_estimate", 0),
                )
                results.append((chunk, float(hit.score)))

        except Exception as exc:
            logger.error("Vector search failed on '%s': %s", self.collection_name, exc)

        return results

    async def delete_file_chunks(self, service_name: str, file_path: str) -> None:
        """Remove all points corresponding to a specific file from Qdrant."""
        client = await get_qdrant_client()
        svc = service_name.lower()
        query_filter = Filter(
            must=[
                FieldCondition(key="service_name", match=MatchValue(value=svc)),
                FieldCondition(key="file_path", match=MatchValue(value=file_path)),
            ]
        )
        try:
            if hasattr(client, "delete"):
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=query_filter,
                )
        except Exception as exc:
            logger.warning("Could not delete file chunks for %s:%s: %s", svc, file_path, exc)

    async def delete_service_chunks(self, service_name: str) -> None:
        """Remove all indexed points belonging to a specific service."""
        client = await get_qdrant_client()
        svc = service_name.lower()
        query_filter = Filter(
            must=[
                FieldCondition(key="service_name", match=MatchValue(value=svc)),
            ]
        )
        try:
            if hasattr(client, "delete"):
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=query_filter,
                )
        except Exception as exc:
            logger.warning("Could not delete service chunks for %s: %s", svc, exc)
