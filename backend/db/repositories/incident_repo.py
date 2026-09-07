"""Repository layer for Incident and IncidentCandidate PostgreSQL persistence."""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy import select, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.incident import Incident, IncidentCandidate
from backend.core.logging import get_logger

logger = get_logger(__name__)


class IncidentRepository:
    """Encapsulates all database operations for Incidents and IncidentCandidates."""

    @staticmethod
    async def create_incident(
        session: AsyncSession,
        title: str,
        primary_service: str,
        affected_services: list[str],
        severity: str = "MEDIUM",
        first_seen: Optional[datetime] = None,
        last_seen: Optional[datetime] = None,
        total_occurrences: int = 1,
        representative_log: Optional[dict] = None,
        summary: Optional[str] = None,
    ) -> Incident:
        """Create and persist a new Incident record."""
        now = datetime.now(timezone.utc)
        incident = Incident(
            id=uuid.uuid4(),
            title=title,
            status="ACTIVE",
            severity=severity,
            primary_service=primary_service,
            affected_services=affected_services,
            total_occurrences=total_occurrences,
            first_seen=first_seen or now,
            last_seen=last_seen or now,
            representative_log=representative_log,
            summary=summary,
        )
        session.add(incident)
        await session.flush()
        return incident

    @staticmethod
    async def add_candidate(
        session: AsyncSession,
        incident_id: uuid.UUID,
        fingerprint: str,
        service_name: str,
        normalized_text: str,
        error_code: Optional[str] = None,
        event_type: Optional[str] = None,
        occurrence_count: int = 1,
        first_seen: Optional[datetime] = None,
        last_seen: Optional[datetime] = None,
        sample_trace_ids: Optional[list[str]] = None,
        representative_log: Optional[dict] = None,
        embedding_id: Optional[str] = None,
    ) -> IncidentCandidate:
        """Create and persist an IncidentCandidate associated with an Incident."""
        now = datetime.now(timezone.utc)
        candidate = IncidentCandidate(
            id=uuid.uuid4(),
            incident_id=incident_id,
            fingerprint=fingerprint,
            service_name=service_name,
            error_code=error_code,
            event_type=event_type,
            normalized_text=normalized_text,
            occurrence_count=occurrence_count,
            first_seen=first_seen or now,
            last_seen=last_seen or now,
            sample_trace_ids=sample_trace_ids or [],
            representative_log=representative_log,
            embedding_id=embedding_id,
        )
        session.add(candidate)
        await session.flush()
        return candidate

    @staticmethod
    async def attach_candidate_to_existing_incident(
        session: AsyncSession,
        incident_id: uuid.UUID,
        fingerprint: str,
        service_name: str,
        normalized_text: str,
        error_code: Optional[str] = None,
        event_type: Optional[str] = None,
        occurrence_count: int = 1,
        first_seen: Optional[datetime] = None,
        last_seen: Optional[datetime] = None,
        sample_trace_ids: Optional[list[str]] = None,
        representative_log: Optional[dict] = None,
        embedding_id: Optional[str] = None,
    ) -> Tuple[Optional[Incident], Optional[IncidentCandidate]]:
        """Attach candidate to existing incident and update aggregate incident stats."""
        # 1. Fetch incident
        stmt = select(Incident).where(Incident.id == incident_id).with_for_update()
        res = await session.execute(stmt)
        incident = res.scalar_one_or_none()
        if not incident or incident.status != "ACTIVE":
            return None, None

        # 2. Check if candidate with same fingerprint already exists in this incident
        now = datetime.now(timezone.utc)
        cand_stmt = (
            select(IncidentCandidate)
            .where(
                IncidentCandidate.incident_id == incident.id,
                IncidentCandidate.fingerprint == fingerprint,
            )
            .limit(1)
        )
        cand_res = await session.execute(cand_stmt)
        existing_candidate = cand_res.scalar_one_or_none()

        if existing_candidate:
            existing_candidate.occurrence_count += occurrence_count
            c_last = last_seen or now
            if c_last > existing_candidate.last_seen:
                existing_candidate.last_seen = c_last
            if sample_trace_ids:
                existing_traces = set(existing_candidate.sample_trace_ids or [])
                for tid in sample_trace_ids:
                    if len(existing_traces) < 10:
                        existing_traces.add(tid)
                existing_candidate.sample_trace_ids = list(existing_traces)
            candidate = existing_candidate
        else:
            candidate = IncidentCandidate(
                id=uuid.uuid4(),
                incident_id=incident.id,
                fingerprint=fingerprint,
                service_name=service_name,
                error_code=error_code,
                event_type=event_type,
                normalized_text=normalized_text,
                occurrence_count=occurrence_count,
                first_seen=first_seen or now,
                last_seen=last_seen or now,
                sample_trace_ids=sample_trace_ids or [],
                representative_log=representative_log,
                embedding_id=embedding_id,
            )
            session.add(candidate)

        # 3. Update Incident stats
        incident.total_occurrences += occurrence_count
        c_last = last_seen or now
        if incident.last_seen is None or c_last > incident.last_seen:
            incident.last_seen = c_last

        # Update affected_services if new service
        services = set(incident.affected_services or [])
        services.add(service_name)
        incident.affected_services = sorted(list(services))

        await session.flush()
        return incident, candidate

    @staticmethod
    async def find_active_incident_by_candidate_fingerprint(
        session: AsyncSession,
        fingerprint: str,
    ) -> Optional[Incident]:
        """Find an active incident that already contains a candidate with the given fingerprint."""
        stmt = (
            select(Incident)
            .join(IncidentCandidate, IncidentCandidate.incident_id == Incident.id)
            .where(
                IncidentCandidate.fingerprint == fingerprint,
                Incident.status == "ACTIVE",
            )
            .order_by(Incident.last_seen.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def update_by_fingerprint_hit(
        session: AsyncSession,
        fingerprint: str,
        additional_count: int,
        last_seen: Optional[datetime] = None,
        trace_ids: Optional[list[str]] = None,
    ) -> Optional[Tuple[Incident, IncidentCandidate]]:
        """Update candidate and parent incident when a fingerprint matches in Redis."""
        # Find candidate by fingerprint
        stmt = (
            select(IncidentCandidate)
            .where(IncidentCandidate.fingerprint == fingerprint)
            .order_by(IncidentCandidate.last_seen.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        candidate = res.scalar_one_or_none()
        if not candidate:
            return None

        now = datetime.now(timezone.utc)
        effective_last_seen = last_seen or now

        # Update candidate
        candidate.occurrence_count += additional_count
        if effective_last_seen > candidate.last_seen:
            candidate.last_seen = effective_last_seen

        if trace_ids:
            existing_traces = set(candidate.sample_trace_ids or [])
            for tid in trace_ids:
                if len(existing_traces) < 10:
                    existing_traces.add(tid)
            candidate.sample_trace_ids = list(existing_traces)

        # Update parent incident
        inc_stmt = select(Incident).where(Incident.id == candidate.incident_id).with_for_update()
        inc_res = await session.execute(inc_stmt)
        incident = inc_res.scalar_one_or_none()
        if incident:
            incident.total_occurrences += additional_count
            if effective_last_seen > incident.last_seen:
                incident.last_seen = effective_last_seen

        await session.flush()
        return incident, candidate

    @staticmethod
    async def get_incident_by_id(
        session: AsyncSession,
        incident_id: uuid.UUID,
    ) -> Optional[Incident]:
        """Fetch an incident by UUID with candidates eagerly loaded."""
        stmt = (
            select(Incident)
            .options(selectinload(Incident.candidates))
            .where(Incident.id == incident_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_candidate_by_fingerprint(
        session: AsyncSession,
        fingerprint: str,
    ) -> Optional[IncidentCandidate]:
        """Retrieve candidate record matching fingerprint."""
        stmt = (
            select(IncidentCandidate)
            .where(IncidentCandidate.fingerprint == fingerprint)
            .order_by(IncidentCandidate.last_seen.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def list_incidents(
        session: AsyncSession,
        status: Optional[str] = None,
        service: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Incident], int]:
        """List incidents with filtering and pagination, returning items and total count."""
        base_query = select(Incident).options(selectinload(Incident.candidates))
        count_query = select(func.count(Incident.id))

        if status:
            base_query = base_query.where(Incident.status == status.upper())
            count_query = count_query.where(Incident.status == status.upper())

        if service:
            base_query = base_query.where(Incident.primary_service == service.lower())
            count_query = count_query.where(Incident.primary_service == service.lower())

        total_count = (await session.execute(count_query)).scalar() or 0

        paginated_query = (
            base_query.order_by(desc(Incident.last_seen))
            .limit(limit)
            .offset(offset)
        )
        items = (await session.execute(paginated_query)).scalars().all()
        return list(items), total_count

    @staticmethod
    async def get_incident_stats(session: AsyncSession) -> dict:
        """Compute aggregated incident statistics."""
        # Total counts by status
        total_stmt = select(func.count(Incident.id))
        active_stmt = select(func.count(Incident.id)).where(Incident.status == "ACTIVE")
        resolved_stmt = select(func.count(Incident.id)).where(Incident.status == "RESOLVED")
        occurrences_stmt = select(func.sum(Incident.total_occurrences))

        total_incidents = (await session.execute(total_stmt)).scalar() or 0
        active_incidents = (await session.execute(active_stmt)).scalar() or 0
        resolved_incidents = (await session.execute(resolved_stmt)).scalar() or 0
        total_occurrences = (await session.execute(occurrences_stmt)).scalar() or 0

        # Services breakdown
        svc_stmt = (
            select(Incident.primary_service, func.count(Incident.id))
            .where(Incident.status == "ACTIVE")
            .group_by(Incident.primary_service)
        )
        svc_counts = dict((await session.execute(svc_stmt)).all())

        return {
            "total_incidents": total_incidents,
            "active_incidents": active_incidents,
            "resolved_incidents": resolved_incidents,
            "total_occurrences": total_occurrences,
            "active_by_service": svc_counts,
        }

    @staticmethod
    async def resolve_incident(
        session: AsyncSession,
        incident_id: uuid.UUID,
    ) -> Optional[Incident]:
        """Mark an incident as RESOLVED."""
        stmt = (
            select(Incident)
            .options(selectinload(Incident.candidates))
            .where(Incident.id == incident_id)
            .with_for_update()
        )
        res = await session.execute(stmt)
        incident = res.scalar_one_or_none()
        if not incident:
            return None

        incident.status = "RESOLVED"
        await session.flush()
        return incident
