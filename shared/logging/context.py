"""Context variable storage for distributed tracing and correlation IDs."""
from contextvars import ContextVar
from typing import Optional
import uuid

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")
_session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
_upstream_service_ctx: ContextVar[Optional[str]] = ContextVar("upstream_service", default=None)


def get_request_id() -> str:
    """Retrieve current request ID or generate a fallback."""
    rid = _request_id_ctx.get()
    if not rid:
        rid = str(uuid.uuid4())
        _request_id_ctx.set(rid)
    return rid


def set_request_id(request_id: str) -> None:
    """Store request ID for the current async context."""
    _request_id_ctx.set(request_id)


def get_trace_id() -> str:
    """Retrieve current distributed trace ID or generate a fallback."""
    tid = _trace_id_ctx.get()
    if not tid:
        tid = str(uuid.uuid4())
        _trace_id_ctx.set(tid)
    return tid


def set_trace_id(trace_id: str) -> None:
    """Store trace ID for the current async context."""
    _trace_id_ctx.set(trace_id)


def get_session_id() -> Optional[str]:
    """Retrieve current session ID."""
    return _session_id_ctx.get()


def set_session_id(session_id: Optional[str]) -> None:
    """Store session ID for the current async context."""
    _session_id_ctx.set(session_id)


def get_upstream_service() -> Optional[str]:
    """Retrieve upstream caller service name."""
    return _upstream_service_ctx.get()


def set_upstream_service(service_name: Optional[str]) -> None:
    """Store upstream service name for the current async context."""
    _upstream_service_ctx.set(service_name)


def set_correlation_context(
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    upstream_service: Optional[str] = None,
) -> tuple[str, str]:
    """Bulk update correlation context and return active (request_id, trace_id)."""
    req_id = request_id or str(uuid.uuid4())
    trc_id = trace_id or str(uuid.uuid4())
    set_request_id(req_id)
    set_trace_id(trc_id)
    set_session_id(session_id)
    set_upstream_service(upstream_service)
    return req_id, trc_id
