"""SQLAlchemy models for Incidents and Incident Candidates."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Boolean,
    Float,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin


class Incident(Base, TimestampMixin):
    """Incident entity representing a clustered set of related microservice failures."""
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="ACTIVE",
        nullable=False,
        index=True,
    )  # "ACTIVE", "RESOLVED"
    severity: Mapped[str] = mapped_column(
        String(32),
        default="MEDIUM",
        nullable=False,
    )  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    primary_service: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    affected_services: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    total_occurrences: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    representative_log: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
    )
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    candidates: Mapped[List["IncidentCandidate"]] = relationship(
        "IncidentCandidate",
        back_populates="incident",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="IncidentCandidate.last_seen.desc()",
    )
    resolution: Mapped[Optional["IncidentResolution"]] = relationship(
        "IncidentResolution",
        back_populates="incident",
        cascade="all, delete-orphan",
        lazy="selectin",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_incidents_status_last_seen", "status", "last_seen"),
        Index("ix_incidents_service_status", "primary_service", "status"),
    )

    def to_dict(self) -> dict:
        """Convert model instance to serializable dictionary."""
        return {
            "id": str(self.id),
            "title": self.title,
            "status": self.status,
            "severity": self.severity,
            "primary_service": self.primary_service,
            "affected_services": self.affected_services or [],
            "total_occurrences": self.total_occurrences,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "representative_log": self.representative_log,
            "summary": self.summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "candidates_count": len(self.candidates) if self.candidates else 0,
            "resolution": self.resolution.to_dict() if getattr(self, "resolution", None) else None,
        }


class IncidentCandidate(Base, TimestampMixin):
    """Incident Candidate representing a deduplicated unique error cluster member."""
    __tablename__ = "incident_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    service_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    error_code: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    event_type: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    normalized_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    sample_trace_ids: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    representative_log: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
    )
    embedding_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    # Relationships
    incident: Mapped["Incident"] = relationship(
        "Incident",
        back_populates="candidates",
    )

    __table_args__ = (
        Index("ix_incident_candidates_fp", "fingerprint"),
        Index("ix_incident_candidates_service_err", "service_name", "error_code"),
    )

    def to_dict(self) -> dict:
        """Convert candidate model instance to serializable dictionary."""
        return {
            "id": str(self.id),
            "incident_id": str(self.incident_id),
            "fingerprint": self.fingerprint,
            "service_name": self.service_name,
            "error_code": self.error_code,
            "event_type": self.event_type,
            "normalized_text": self.normalized_text,
            "occurrence_count": self.occurrence_count,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "sample_trace_ids": self.sample_trace_ids or [],
            "representative_log": self.representative_log,
            "embedding_id": self.embedding_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class IncidentResolution(Base, TimestampMixin):
    """Persistent Incident Memory storing verified root causes, suggested fixes, and human review."""
    __tablename__ = "incident_resolutions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_summary: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fix: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    human_approval: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # True=Approved, False=Rejected, None=Pending
    reviewer_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="AWAITING_APPROVAL", nullable=False)
    affected_services: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    inspected_files: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    inspected_symbols: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    consulted_docs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    blast_radius: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    references: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    reasoning_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reused_incident_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Relationships
    incident: Mapped["Incident"] = relationship(
        "Incident",
        back_populates="resolution",
    )

    __table_args__ = (
        Index("ix_incident_resolutions_status", "status"),
        Index("ix_incident_resolutions_approval", "human_approval"),
    )

    def to_dict(self) -> dict:
        """Convert resolution instance to serializable dictionary."""
        return {
            "id": str(self.id),
            "incident_id": str(self.incident_id),
            "root_cause": self.root_cause,
            "resolution_summary": self.resolution_summary,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
            "human_approval": self.human_approval,
            "reviewer_feedback": self.reviewer_feedback,
            "status": self.status,
            "affected_services": self.affected_services or [],
            "inspected_files": self.inspected_files or [],
            "inspected_symbols": self.inspected_symbols or [],
            "consulted_docs": self.consulted_docs or [],
            "blast_radius": self.blast_radius,
            "references": self.references or [],
            "reasoning_summary": self.reasoning_summary,
            "reused_incident_id": self.reused_incident_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

