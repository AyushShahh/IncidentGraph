"""FastAPI middleware for trace propagation and automated HTTP request logging."""
import time
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from shared.logging.context import (
    set_correlation_context,
    get_trace_id,
    get_request_id,
    get_session_id,
)
from shared.logging.logger import get_service_logger


def is_health_path(path: str) -> bool:
    """Detect if request path is a health check endpoint."""
    clean = path.rstrip("/")
    return (
        clean == "/health"
        or clean.startswith("/health/")
        or clean.endswith("/health")
        or clean.endswith("/health/ready")
        or clean.endswith("/health/live")
        or "/health/" in path
    )


class TraceCorrelationMiddleware(BaseHTTPMiddleware):
    """Intercepts requests to extract/generate tracing IDs and log lifecycle events."""

    def __init__(self, app, service_name: str) -> None:
        super().__init__(app)
        self.service_name = service_name
        self.logger = get_service_logger(service_name)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract headers (case-insensitive in ASGI)
        req_id = request.headers.get("x-request-id")
        trace_id = request.headers.get("x-trace-id")
        session_id = request.headers.get("x-session-id")
        upstream_service = request.headers.get("x-upstream-service")

        # Set ambient context variables
        set_correlation_context(
            request_id=req_id,
            trace_id=trace_id,
            session_id=session_id,
            upstream_service=upstream_service,
        )

        is_health = is_health_path(request.url.path)
        start_time = time.perf_counter()

        # Suppress http_request log for health checks to eliminate noise
        if not is_health:
            self.logger.info(
                f"Incoming {request.method} {request.url.path}",
                event_type="http_request",
                attributes={
                    "method": request.method,
                    "path": request.url.path,
                    "client_ip": request.client.host if request.client else None,
                },
            )

        try:
            response: Response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # Add tracing headers to response
            response.headers["x-request-id"] = get_request_id()
            response.headers["x-trace-id"] = get_trace_id()
            active_session_id = get_session_id()
            if active_session_id:
                response.headers["x-session-id"] = active_session_id

            # Filter health check logs: skip if successful (< 400), log error if failed (>= 400)
            if is_health:
                if response.status_code >= 400:
                    self.logger.error(
                        f"Health check failed: {request.method} {request.url.path} returned {response.status_code} in {duration_ms}ms",
                        event_type="health_check_failed",
                        attributes={
                            "status_code": response.status_code,
                            "duration_ms": duration_ms,
                            "path": request.url.path,
                        },
                    )
                return response

            # Standard request/response logging for non-health endpoints
            log_fn = self.logger.info if response.status_code < 400 else self.logger.warning
            log_fn(
                f"Completed {request.method} {request.url.path} with status {response.status_code} in {duration_ms}ms",
                event_type="http_response",
                attributes={
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            event_type = "health_check_failed" if is_health else "error"
            self.logger.error(
                f"Unhandled exception during {request.method} {request.url.path} after {duration_ms}ms: {exc}",
                event_type=event_type,
                exception=exc,
                attributes={
                    "duration_ms": duration_ms,
                    "path": request.url.path,
                },
            )
            raise exc
