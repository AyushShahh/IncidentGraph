"""Instrumented HTTP client for inter-service communication with connection pooling and trace propagation."""
from typing import Any, Optional
import httpx
from shared.logging.context import (
    get_request_id,
    get_trace_id,
    get_session_id,
)
from shared.logging.logger import get_service_logger


class ServiceHttpClient:
    """Inter-service HTTP client propagating tracing context and reusing connections."""

    def __init__(
        self,
        caller_service: str,
        timeout: float = 10.0,
        max_keepalive_connections: int = 20,
        max_connections: int = 50,
    ) -> None:
        self.caller_service = caller_service
        self.logger = get_service_logger(caller_service)
        self.default_timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_keepalive_connections=max_keepalive_connections,
                max_connections=max_connections,
            ),
        )

    async def close(self) -> None:
        """Close persistent HTTP client session."""
        if not self._client.is_closed:
            await self._client.aclose()

    def _prepare_headers(self, custom_headers: Optional[dict[str, str]] = None) -> dict[str, str]:
        """Inject ambient correlation headers."""
        headers = {
            "x-request-id": get_request_id(),
            "x-trace-id": get_trace_id(),
            "x-upstream-service": self.caller_service,
        }
        session_id = get_session_id()
        if session_id:
            headers["x-session-id"] = session_id
        if custom_headers:
            headers.update(custom_headers)
        return headers

    async def get(
        self,
        url: str,
        target_service: str,
        client: Optional[httpx.AsyncClient] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Execute GET request with tracing propagation and connection reuse."""
        merged_headers = self._prepare_headers(headers)
        self.logger.info(
            f"Dispatching GET to downstream service '{target_service}' at {url}",
            event_type="service_call",
            downstream_service=target_service,
            attributes={"url": url, "method": "GET"},
        )
        active_client = client or self._client
        req_timeout = timeout if timeout is not None else self.default_timeout
        return await active_client.get(url, headers=merged_headers, timeout=req_timeout)

    async def post(
        self,
        url: str,
        target_service: str,
        json_data: Optional[dict[str, Any]] = None,
        client: Optional[httpx.AsyncClient] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Execute POST request with tracing propagation and connection reuse."""
        merged_headers = self._prepare_headers(headers)
        self.logger.info(
            f"Dispatching POST to downstream service '{target_service}' at {url}",
            event_type="service_call",
            downstream_service=target_service,
            attributes={"url": url, "method": "POST"},
        )
        active_client = client or self._client
        req_timeout = timeout if timeout is not None else self.default_timeout
        return await active_client.post(url, json=json_data, headers=merged_headers, timeout=req_timeout)
