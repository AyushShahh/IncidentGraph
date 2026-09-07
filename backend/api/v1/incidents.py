"""REST API endpoints for incident management, candidate inspection, and statistics."""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db_session
from backend.db.repositories.incident_repo import IncidentRepository
from backend.clustering.redis_index import redis_index
from backend.clustering.vector_index import vector_index
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("", summary="List incidents with filtering and pagination")
async def list_incidents(
    status: Optional[str] = Query(None, description="Filter by status ('ACTIVE' or 'RESOLVED')"),
    service: Optional[str] = Query(None, description="Filter by primary service name"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    offset: int = Query(0, ge=0, description="Page offset"),
    session: AsyncSession = Depends(get_db_session),
):
    """Retrieve paginated incidents matching filter criteria."""
    items, total = await IncidentRepository.list_incidents(
        session=session,
        status=status,
        service=service,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [inc.to_dict() for inc in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats/summary", summary="Retrieve aggregated incident statistics")
async def get_incident_stats(
    session: AsyncSession = Depends(get_db_session),
):
    """Get high-level statistics across all tracked incidents."""
    return await IncidentRepository.get_incident_stats(session=session)


@router.get("/{incident_id}", summary="Get detailed incident by ID with constituent candidates")
async def get_incident(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """Fetch an incident by UUID, including all clustered candidates and sample logs."""
    incident = await IncidentRepository.get_incident_by_id(session=session, incident_id=incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    result = incident.to_dict()
    result["candidates"] = [c.to_dict() for c in incident.candidates]
    return result


@router.post("/{incident_id}/resolve", summary="Mark incident resolved and prune indexes")
async def resolve_incident(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """Mark an incident as RESOLVED, purge its fingerprints from Redis, and remove vectors from Qdrant."""
    incident = await IncidentRepository.resolve_incident(session=session, incident_id=incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Clean up Redis active fingerprint mappings
    fingerprints = [c.fingerprint for c in incident.candidates]
    if fingerprints:
        await redis_index.delete_fingerprints(fingerprints)
        logger.info("Deleted %d fingerprints from Redis for incident %s", len(fingerprints), incident_id)

    # Clean up Qdrant vectors
    await vector_index.delete_incident_vectors(incident_id)
    logger.info("Deleted Qdrant candidate vectors for incident %s", incident_id)

    return {
        "message": f"Incident {incident_id} marked as RESOLVED and active indexes pruned",
        "incident": incident.to_dict(),
    }
