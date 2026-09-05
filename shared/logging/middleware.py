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
            if response.status_code >= 500:
                error_code = response.headers.get("x-error-code") or f"HTTP_{response.status_code}"
                self.logger.error(
                    f"Server error on {request.method} {request.url.path}: status {response.status_code} in {duration_ms}ms [{error_code}]",
                    event_type="http_response_error",
                    error_code=error_code,
                    attributes={
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                        "error_code": error_code,
                        "path": request.url.path,
                        "method": request.method,
                    },
                )
            elif response.status_code >= 400:
                error_code = response.headers.get("x-error-code") or f"HTTP_{response.status_code}"
                self.logger.warning(
                    f"Client error on {request.method} {request.url.path}: status {response.status_code} in {duration_ms}ms [{error_code}]",
                    event_type="http_response_warning",
                    error_code=error_code,
                    attributes={
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                        "error_code": error_code,
                        "path": request.url.path,
                        "method": request.method,
                    },
                )
            else:
                self.logger.info(
                    f"Completed {request.method} {request.url.path} with status {response.status_code} in {duration_ms}ms",
                    event_type="http_response",
                    attributes={
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                        "path": request.url.path,
                        "method": request.method,
                    },
                )
            return response

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            event_type = "health_check_failed" if is_health else "unhandled_exception"
            error_code = getattr(exc, "error_code", None) or type(exc).__name__
            status_code = getattr(exc, "status_code", 500)

            self.logger.error(
                f"Unhandled exception during {request.method} {request.url.path} after {duration_ms}ms: {type(exc).__name__}: {exc}",
                event_type=event_type,
                error_code=error_code,
                exception=exc,
                attributes={
                    "duration_ms": duration_ms,
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": status_code,
                    "error_code": error_code,
                    "exception_type": type(exc).__name__,
                },
            )
            from starlette.responses import JSONResponse
            err_resp = JSONResponse(
                status_code=status_code,
                content={
                    "error": error_code,
                    "detail": str(exc),
                    "exception_type": type(exc).__name__,
                },
            )
            err_resp.headers["x-request-id"] = get_request_id()
            err_resp.headers["x-trace-id"] = get_trace_id()
            err_resp.headers["x-error-code"] = str(error_code)
            active_session_id = get_session_id()
            if active_session_id:
                err_resp.headers["x-session-id"] = active_session_id
            return err_resp
