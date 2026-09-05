"""Configurable failure injector simulating real-world distributed faults."""
import os
import random
from typing import Optional
from fastapi import HTTPException
from pydantic import BaseModel
from shared.logging.logger import get_service_logger


class DatabaseTimeoutException(Exception):
    """Simulated database query / connection timeout."""
    pass


class NetworkTimeoutException(Exception):
    """Simulated downstream HTTP socket / network timeout."""
    pass


class RetryExhaustionException(Exception):
    """Simulated retry budget exhausted across multiple attempts."""
    pass


class FailureConfigRequest(BaseModel):
    """Payload for runtime failure simulation reconfiguration."""
    failure_rate: Optional[float] = None
    enabled_failures: Optional[list[str]] = None
    trigger_after_n_calls: Optional[int] = None
    target_service: Optional[str] = None


class FailureInjector:
    """Simulates production failures across microservices.

    Supported Failure Modes:
    - 'database_timeout': Database query timeout (raises DatabaseTimeoutException)
    - 'network_timeout': Downstream connection timeout (raises NetworkTimeoutException)
    - 'http_500': Internal server error (raises HTTPException 500)
    - 'authentication_failure': Unauthorized request (raises HTTPException 401)
    - 'retry_exhaustion': Max retry attempts exceeded (raises RetryExhaustionException)
    """

    ALL_FAILURES = [
        "database_timeout",
        "network_timeout",
        "http_500",
        "authentication_failure",
        "retry_exhaustion",
    ]

    def __init__(
        self,
        service_name: str = "generic-service",
        failure_rate: Optional[float] = None,
        enabled_failures: Optional[list[str]] = None,
        trigger_after_n_calls: int = 0,
    ) -> None:
        self.service_name = service_name
        self.failure_rate = (
            failure_rate
            if failure_rate is not None
            else float(os.getenv("FAILURE_RATE", "0.0"))
        )
        self.enabled_failures = enabled_failures or list(self.ALL_FAILURES)
        self.trigger_after_n_calls = trigger_after_n_calls
        self.call_count = 0
        self.logger = get_service_logger(service_name)

    def configure(
        self,
        failure_rate: Optional[float] = None,
        enabled_failures: Optional[list[str]] = None,
        trigger_after_n_calls: Optional[int] = None,
    ) -> None:
        """Dynamically update failure simulation settings."""
        if failure_rate is not None:
            self.failure_rate = max(0.0, min(1.0, float(failure_rate)))
        if enabled_failures is not None:
            self.enabled_failures = [f for f in enabled_failures if f in self.ALL_FAILURES]
        if trigger_after_n_calls is not None:
            self.trigger_after_n_calls = max(0, int(trigger_after_n_calls))

    def reset_counts(self) -> None:
        """Reset internal invocation counter."""
        self.call_count = 0

    def should_fail(self) -> bool:
        """Determine if current invocation should trigger a failure."""
        self.call_count += 1
        # Traffic initially succeeds until trigger_after_n_calls threshold is reached
        if self.call_count <= self.trigger_after_n_calls:
            return False
        if self.failure_rate <= 0.0 or not self.enabled_failures:
            return False
        return random.random() < self.failure_rate

    def inject_failure_if_needed(
        self,
        operation_name: str,
        specific_mode: Optional[str] = None,
    ) -> None:
        """Inspect failure criteria and raise simulated exception if triggered."""
        if not self.should_fail() and not specific_mode:
            return

        mode = specific_mode or random.choice(self.enabled_failures)

        self.logger.error(
            f"Simulating failure mode '{mode}' during operation '{operation_name}'",
            event_type="failure_simulation",
            attributes={
                "operation": operation_name,
                "failure_mode": mode,
                "failure_rate": self.failure_rate,
                "call_count": self.call_count,
            },
        )

        if mode == "database_timeout":
            raise DatabaseTimeoutException(
                f"Simulated DB timeout on operation '{operation_name}' after 5000ms"
            )
        elif mode == "network_timeout":
            raise NetworkTimeoutException(
                f"Simulated downstream connection timeout on operation '{operation_name}'"
            )
        elif mode == "http_500":
            raise HTTPException(
                status_code=500,
                detail=f"Simulated Internal Server Error during '{operation_name}'",
            )
        elif mode == "authentication_failure":
            raise HTTPException(
                status_code=401,
                detail=f"Simulated Authentication Failure: Invalid service token for '{operation_name}'",
            )
        elif mode == "retry_exhaustion":
            raise RetryExhaustionException(
                f"Simulated Retry Exhaustion: 3 attempts failed during '{operation_name}'"
            )


_shared_injectors: dict[str, FailureInjector] = {}


def get_shared_failure_injector(service_name: str = "generic") -> FailureInjector:
    """Get or create singleton FailureInjector for a service."""
    if service_name not in _shared_injectors:
        _shared_injectors[service_name] = FailureInjector(service_name=service_name)
    return _shared_injectors[service_name]
