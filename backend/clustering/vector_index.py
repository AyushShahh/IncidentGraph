"""Qdrant vector index management for active incident candidate embeddings."""
import uuid
from typing import List, Optional, Dict, Any
from qdrant_client.http.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

from backend.qdrant.client import get_qdrant_client
from backend.core.config import settings
from backend.core.logging import get_logger
from shared.constants import QDRANT_ACTIVE_INCIDENTS_COLLECTION

logger = get_logger(__name__)


class QdrantVectorIndex:
    """Manages indexing and semantic similarity search of active incident candidate vectors in Qdrant."""

    def __init__(self, collection_name: str = QDRANT_ACTIVE_INCIDENTS_COLLECTION):
        self.collection_name = collection_name

    async def ensure_collection(self, vector_dim: int = 384) -> None:
        """Create the active incidents collection if it does not exist."""
        client = await get_qdrant_client()
        exists = await client.collection_exists(self.collection_name)
        if not exists:
            logger.info(
                "Creating Qdrant collection '%s' (dim=%d, distance=COSINE)...",
                self.collection_name,
                vector_dim,
            )
            await client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE),
            )

    async def search_nearest_active_candidate(
        self,
        embedding: List[float],
        score_threshold: Optional[float] = None,
        service_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Search for the most semantically similar active incident candidate.

        Args:
            embedding: Normalized dense query vector.
            score_threshold: Minimum cosine similarity score (defaults to settings.SIMILARITY_THRESHOLD).
            service_name: Optional service name filter.

        Returns:
            Dict containing match info ('incident_id', 'candidate_id', 'score', 'payload') or None.
        """
        threshold = score_threshold if score_threshold is not None else settings.SIMILARITY_THRESHOLD
        client = await get_qdrant_client()

        query_filter = None
        if service_name:
            query_filter = Filter(
                must=[FieldCondition(key="service_name", match=MatchValue(value=service_name))]
            )

        try:
            # AsyncQdrantClient uses query_points or search_points
            if hasattr(client, "query_points"):
                res = await client.query_points(
                    collection_name=self.collection_name,
                    query=embedding,
                    query_filter=query_filter,
                    limit=1,
                    score_threshold=threshold,
                )
                search_result = res.points if hasattr(res, "points") else res
            elif hasattr(client, "search_points"):
                search_result = await client.search_points(
                    collection_name=self.collection_name,
                    vector=embedding,
                    query_filter=query_filter,
                    limit=1,
                    score_threshold=threshold,
                )
            elif hasattr(client, "search"):
                search_result = await client.search(
                    collection_name=self.collection_name,
                    query_vector=embedding,
                    query_filter=query_filter,
                    limit=1,
                    score_threshold=threshold,
                )
            else:
                search_result = []

            if search_result:
                top_hit = search_result[0]
                payload = top_hit.payload or {}
                incident_id = payload.get("incident_id")
                if incident_id:
                    return {
                        "incident_id": incident_id,
                        "candidate_id": str(top_hit.id),
                        "score": top_hit.score,
                        "payload": payload,
                    }
        except Exception as exc:
            logger.error("Error during Qdrant vector similarity search: %s", exc)

        return None

    async def insert_candidate_vector(
        self,
        candidate_id: uuid.UUID | str,
        incident_id: uuid.UUID | str,
        fingerprint: str,
        service_name: str,
        embedding: List[float],
        error_code: Optional[str] = None,
        timestamp: Optional[str] = None,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert or update a candidate vector with mandatory metadata payload."""
        client = await get_qdrant_client()
        cid_str = str(candidate_id)

        payload: Dict[str, Any] = {
            "incident_id": str(incident_id),
            "candidate_id": cid_str,
            "fingerprint": fingerprint,
            "service_name": service_name,
            "error_code": error_code,
            "timestamp": timestamp,
            "status": "ACTIVE",
        }
        if extra_payload:
            payload.update(extra_payload)

        point = PointStruct(
            id=cid_str,
            vector=embedding,
            payload=payload,
        )

        await client.upsert(
            collection_name=self.collection_name,
            points=[point],
        )

    async def insert_candidate_vectors_batch(
        self,
        points_data: List[Dict[str, Any]],
    ) -> None:
        """Batch upsert candidate vectors into Qdrant."""
        if not points_data:
            return

        client = await get_qdrant_client()
        points: List[PointStruct] = []

        for item in points_data:
            cid_str = str(item["candidate_id"])
            payload: Dict[str, Any] = {
                "incident_id": str(item["incident_id"]),
                "candidate_id": cid_str,
                "fingerprint": item["fingerprint"],
                "service_name": item["service_name"],
                "error_code": item.get("error_code"),
                "timestamp": item.get("timestamp"),
                "status": "ACTIVE",
            }
            if "extra_payload" in item and item["extra_payload"]:
                payload.update(item["extra_payload"])

            points.append(
                PointStruct(
                    id=cid_str,
                    vector=item["embedding"],
                    payload=payload,
                )
            )

        await client.upsert(
            collection_name=self.collection_name,
            points=points,
        )

    async def delete_incident_vectors(self, incident_id: uuid.UUID | str) -> None:
        """Remove all candidate vectors belonging to an incident upon resolution."""
        client = await get_qdrant_client()
        inc_str = str(incident_id)

        delete_filter = Filter(
            must=[FieldCondition(key="incident_id", match=MatchValue(value=inc_str))]
        )

        logger.info("Purging Qdrant vectors for resolved incident %s", inc_str)
        await client.delete(
            collection_name=self.collection_name,
            points_selector=delete_filter,
        )

    async def clear_all_vectors(self) -> None:
        """Remove all points from the collection (for tests/resets)."""
        client = await get_qdrant_client()
        exists = await client.collection_exists(self.collection_name)
        if exists:
            # Delete with empty filter matches all points
            await client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(must=[]),
            )


vector_index = QdrantVectorIndex()
