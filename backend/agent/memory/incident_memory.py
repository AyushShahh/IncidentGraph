"""Incident Memory layer backed by PostgreSQL and Qdrant for storing and retrieving resolutions."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from qdrant_client.http.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.clustering.embeddings.factory import get_embedding_provider
from backend.core.config import settings
from backend.core.logging import get_logger
from backend.models.incident import Incident, IncidentResolution
from backend.qdrant.client import get_qdrant_client
from shared.constants import QDRANT_INCIDENT_COLLECTION

logger = get_logger(__name__)


class IncidentMemory:
    """Manages Layer 2 Incident Memory: persistent PostgreSQL records and Qdrant semantic resolutions."""

    def __init__(self, collection_name: str = QDRANT_INCIDENT_COLLECTION) -> None:
        self.collection_name = collection_name
        self.threshold = settings.STAGE4_MEMORY_SIMILARITY_THRESHOLD

    async def search_similar_resolution(
        self,
        query_text: str,
        service: Optional[str] = None,
        threshold: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Search Qdrant for a previously approved resolution matching the incident problem profile.

        Returns:
            Dict containing match info ('incident_id', 'root_cause', 'suggested_fix', 'score') or None.
        """
        score_cutoff = threshold if threshold is not None else self.threshold
        provider = get_embedding_provider()
        client = await get_qdrant_client()

        try:
            exists = await client.collection_exists(self.collection_name)
            if not exists:
                return None

            query_vector = await provider.embed_text(query_text)
        except Exception as exc:
            logger.warning("Failed embedding incident memory query: %s", exc)
            return None

        # Filter only for APPROVED resolutions in the target service if provided
        must_conditions = [
            FieldCondition(key="status", match=MatchValue(value="APPROVED"))
        ]
        if service:
            must_conditions.append(
                FieldCondition(key="service", match=MatchValue(value=service.lower()))
            )

        query_filter = Filter(must=must_conditions)

        try:
            if hasattr(client, "query_points"):
                res = await client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=query_filter,
                    limit=1,
                    score_threshold=score_cutoff,
                )
                hits = res.points if hasattr(res, "points") else res
            elif hasattr(client, "search_points"):
                hits = await client.search_points(
                    collection_name=self.collection_name,
                    vector=query_vector,
                    query_filter=query_filter,
                    limit=1,
                    score_threshold=score_cutoff,
                )
            elif hasattr(client, "search"):
                hits = await client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=1,
                    score_threshold=score_cutoff,
                )
            else:
                hits = []

            if hits:
                top_hit = hits[0]
                payload = top_hit.payload or {}
                return {
                    "incident_id": payload.get("incident_id"),
                    "service": payload.get("service"),
                    "root_cause": payload.get("root_cause"),
                    "suggested_fix": payload.get("suggested_fix"),
                    "resolution_summary": payload.get("resolution_summary"),
                    "confidence": payload.get("confidence", 1.0),
                    "score": round(float(top_hit.score), 3),
                }
        except Exception as exc:
            logger.warning("Error searching Qdrant incident resolutions: %s", exc)

        return None

    async def store_resolution(
        self,
        session: AsyncSession,
        incident_id: str,
        resolution_data: Dict[str, Any],
        approved: bool = True,
        reviewer_feedback: Optional[str] = None,
    ) -> IncidentResolution:
        """Persist or update resolution in PostgreSQL and index into Qdrant for semantic reuse."""
        def to_uuid(val: Any) -> uuid.UUID:
            if isinstance(val, uuid.UUID):
                return val
            try:
                return uuid.UUID(str(val))
            except (ValueError, AttributeError):
                return uuid.uuid5(uuid.NAMESPACE_DNS, str(val))

        inc_uuid = to_uuid(incident_id)

        aff_services = resolution_data.get("affected_services", [])
        if not aff_services and "primary_service" in resolution_data:
            aff_services = [resolution_data["primary_service"]]

        # Ensure parent incident exists in PostgreSQL so Foreign Key constraint is satisfied
        inc_stmt = select(Incident).where(Incident.id == inc_uuid)
        inc_res = await session.execute(inc_stmt)
        parent_incident = inc_res.scalar_one_or_none()
        if parent_incident is None:
            primary_svc = aff_services[0] if aff_services else "unknown"
            parent_incident = Incident(
                id=inc_uuid,
                title=f"Incident {incident_id}",
                primary_service=primary_svc,
                severity="HIGH",
                status="RESOLVED" if approved else "INVESTIGATING",
                summary=resolution_data.get("resolution_summary", ""),
            )
            session.add(parent_incident)
            await session.flush()
        else:
            if not aff_services and parent_incident.primary_service:
                aff_services = [parent_incident.primary_service]
            if approved:
                parent_incident.status = "RESOLVED"

        # 1. Update or create PostgreSQL record
        stmt = select(IncidentResolution).where(IncidentResolution.incident_id == inc_uuid)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        status_str = "APPROVED" if approved else "REJECTED"

        if record is None:
            record = IncidentResolution(
                id=uuid.uuid4(),
                incident_id=inc_uuid,
                root_cause=resolution_data.get("root_cause", ""),
                resolution_summary=resolution_data.get("resolution_summary", ""),
                suggested_fix=resolution_data.get("suggested_fix", ""),
                confidence=float(resolution_data.get("confidence", 0.9)),
                human_approval=approved,
                reviewer_feedback=reviewer_feedback,
                status=status_str,
                affected_services=aff_services,
                inspected_files=resolution_data.get("inspected_files", []),
                inspected_symbols=resolution_data.get("inspected_symbols", []),
                consulted_docs=resolution_data.get("consulted_docs", []),
                blast_radius=resolution_data.get("blast_radius"),
                references=resolution_data.get("references", []),
                reasoning_summary=resolution_data.get("reasoning_summary"),
                reused_incident_id=resolution_data.get("reused_incident_id"),
            )
            session.add(record)
        else:
            record.root_cause = resolution_data.get("root_cause", record.root_cause)
            record.resolution_summary = resolution_data.get("resolution_summary", record.resolution_summary)
            record.suggested_fix = resolution_data.get("suggested_fix", record.suggested_fix)
            record.confidence = float(resolution_data.get("confidence", record.confidence))
            record.human_approval = approved
            record.reviewer_feedback = reviewer_feedback
            record.status = status_str
            if not record.affected_services and aff_services:
                record.affected_services = aff_services
            else:
                record.affected_services = resolution_data.get("affected_services", record.affected_services)
            record.inspected_files = resolution_data.get("inspected_files", record.inspected_files)
            record.inspected_symbols = resolution_data.get("inspected_symbols", record.inspected_symbols)
            record.consulted_docs = resolution_data.get("consulted_docs", record.consulted_docs)
            record.blast_radius = resolution_data.get("blast_radius", record.blast_radius)
            record.references = resolution_data.get("references", record.references)
            record.reasoning_summary = resolution_data.get("reasoning_summary", record.reasoning_summary)
            record.reused_incident_id = resolution_data.get("reused_incident_id", record.reused_incident_id)

        await session.commit()
        await session.refresh(record)

        # 2. Index into Qdrant if approved (only approved resolutions become reusable memory)
        if approved:
            await self._index_resolution_in_qdrant(str(inc_uuid), record)

        return record

    async def _index_resolution_in_qdrant(self, incident_id_str: str, record: IncidentResolution) -> None:
        """Upsert semantic embedding for approved resolution into Qdrant."""
        provider = get_embedding_provider()
        client = await get_qdrant_client()

        # Text representation focusing on problem symptoms and root cause for high-precision matching
        services_str = ", ".join(record.affected_services) if record.affected_services else "unknown"
        text_to_embed = f"{services_str}: {record.root_cause}"

        try:
            emb = await provider.embed_text(text_to_embed)
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"resolution:{incident_id_str}"))

            primary_svc = record.affected_services[0].lower() if record.affected_services else "unknown"
            payload = {
                "incident_id": incident_id_str,
                "service": primary_svc,
                "service_name": primary_svc,
                "root_cause": record.root_cause,
                "resolution_summary": record.resolution_summary,
                "suggested_fix": record.suggested_fix,
                "confidence": record.confidence,
                "status": "APPROVED",
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }

            await client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=emb,
                        payload=payload,
                    )
                ],
            )
            logger.info("Indexed approved resolution for incident %s into Qdrant '%s'.", incident_id_str, self.collection_name)
        except Exception as exc:
            logger.warning("Failed indexing resolution into Qdrant: %s", exc)


# Global singleton instance
incident_memory = IncidentMemory()
