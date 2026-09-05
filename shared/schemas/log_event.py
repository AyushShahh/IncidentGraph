"""Canonical log event schema emitted by all microservices to Kafka."""
from datetime import datetime, timezone
import os
import socket
from typing import Any, Optional
import uuid
from pydantic import BaseModel, Field, field_serializer


def _default_instance_id() -> str:
    """Generate default instance ID based on container hostname or random uuid."""
    return os.getenv("INSTANCE_ID") or os.getenv("HOSTNAME") or socket.gethostname() or str(uuid.uuid4())[:8]


class LogEventSchema(BaseModel):
    """Canonical log event schema for distributed microservices logging."""

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO-8601 UTC timestamp of the log event",
    )
    service_name: str = Field(
        ...,
        description="Originating service identifier (e.g., gateway, orders, payments)",
    )
    instance_id: str = Field(
        default_factory=_default_instance_id,
        description="Unique container/pod/process instance identifier",
    )
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique request correlation ID",
    )
    trace_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Distributed trace ID propagated across service hops",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session or user identifier associated with request",
    )
    log_level: str = Field(
        default="INFO",
        description="Log severity: DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )
    event_type: str = Field(
        default="application_event",
        description="Classification: http_request, http_response, service_call, failure_simulation, error, etc.",
    )
    message: str = Field(
        ...,
        description="Descriptive log message text",
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Machine-readable error code, e.g. ZERO_DIVISION_ERROR, INDEX_OUT_OF_BOUNDS, DB_POOL_EXHAUSTED",
    )
    exception: Optional[str] = Field(
        default=None,
        description="Serialized stack trace or exception string if an error occurred",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary additional key-value payload attributes",
    )
    upstream_service: Optional[str] = Field(
        default=None,
        description="Name of the calling upstream service",
    )
    downstream_service: Optional[str] = Field(
        default=None,
        description="Name of the callee downstream service if making an outbound request",
    )
    deployment_version: str = Field(
        default="v1.0.0",
        description="Current release or deployment version",
    )
    environment: str = Field(
        default="development",
        description="Target runtime environment (development, staging, production)",
    )

    @field_serializer("timestamp")
    def serialize_timestamp(self, dt: datetime, _info) -> str:
        return dt.isoformat()
