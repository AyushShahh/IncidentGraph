"""REST API endpoints for global system telemetry, incident statistics, and event logs."""
from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db_session
from backend.models.incident import Incident, IncidentCandidate, IncidentResolution
from backend.api.v1.ws import ws_manager

router = APIRouter()


@router.get("", summary="Get aggregated platform statistics and KPI metrics")
async def get_platform_stats(session: AsyncSession = Depends(get_db_session)) -> Dict[str, Any]:
    """Calculate platform KPI stats across incidents, candidates, and memory resolutions."""
    # 1. Incident counts by status
    total_incidents_q = await session.execute(select(func.count(Incident.id)))
    total_incidents = total_incidents_q.scalar() or 0

    active_incidents_q = await session.execute(
        select(func.count(Incident.id)).where(Incident.status == "ACTIVE")
    )
    active_incidents = active_incidents_q.scalar() or 0

    resolved_incidents_q = await session.execute(
        select(func.count(Incident.id)).where(Incident.status == "RESOLVED")
    )
    resolved_incidents = resolved_incidents_q.scalar() or 0

    # 2. Total occurrences / log candidates volume
    total_occurrences_q = await session.execute(select(func.sum(Incident.total_occurrences)))
    total_occurrences = total_occurrences_q.scalar() or 0

    total_candidates_q = await session.execute(select(func.count(IncidentCandidate.id)))
    total_candidates = total_candidates_q.scalar() or 0

    # 3. Memory & resolution stats
    resolutions_q = await session.execute(select(func.count(IncidentResolution.id)))
    total_resolutions = resolutions_q.scalar() or 0

    approved_q = await session.execute(
        select(func.count(IncidentResolution.id)).where(IncidentResolution.human_approval == True)  # noqa: E712
    )
    approved_resolutions = approved_q.scalar() or 0

    # 4. Service-level incident distribution
    svc_dist_q = await session.execute(
        select(Incident.primary_service, func.count(Incident.id))
        .group_by(Incident.primary_service)
    )
    service_distribution = {svc: count for svc, count in svc_dist_q.all()}

    # Calculate auto-resolve and approval rate
    auto_resolve_rate = (
        round((resolved_incidents / total_incidents) * 100, 1) if total_incidents > 0 else 0.0
    )

    return {
        "total_incidents": total_incidents,
        "active_incidents": active_incidents,
        "resolved_incidents": resolved_incidents,
        "total_occurrences": total_occurrences,
        "total_candidates": total_candidates,
        "total_resolutions": total_resolutions,
        "approved_resolutions": approved_resolutions,
        "auto_resolve_rate_percent": auto_resolve_rate,
        "service_distribution": service_distribution,
    }


@router.get("/events", summary="Get recent live event stream history")
async def get_recent_events() -> List[Dict[str, Any]]:
    """Return in-memory recent event history stream."""
    return ws_manager.get_history()
