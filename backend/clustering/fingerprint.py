"""Deterministic SHA256 fingerprint generation for error logs."""
import hashlib
from typing import Optional


def generate_fingerprint(
    service_name: str,
    normalized_text: str,
    error_code: Optional[str] = None,
    event_type: Optional[str] = None,
    endpoint: Optional[str] = None,
    deployment_version: Optional[str] = None,
) -> str:
    """Generate a stable, deterministic SHA256 hex fingerprint for an incident candidate.

    Stable inputs ensure that logs differing only in dynamic runtime variables
    (e.g., timestamps, UUIDs, request IDs) resolve to the exact same fingerprint.
    """
    svc = (service_name or "unknown").strip().lower()
    err = (error_code or "").strip().upper()
    evt = (event_type or "").strip().lower()
    ep = (endpoint or "").strip().lower()
    ver = (deployment_version or "").strip().lower()
    norm = (normalized_text or "").strip()

    # Canonical representation
    canonical_string = f"{svc}|{err}|{evt}|{ep}|{ver}|{norm}"
    return hashlib.sha256(canonical_string.encode("utf-8")).hexdigest()


def fingerprint_log(log: dict, normalized_text: str) -> str:
    """Extract fields from a structured log dictionary and compute its fingerprint."""
    service_name = log.get("service") or log.get("service_name") or "unknown"

    # Extract error_code
    error_info = log.get("error") or {}
    error_code = log.get("error_code")
    if not error_code:
        if isinstance(error_info, dict):
            error_code = error_info.get("error_code") or error_info.get("type")
        elif isinstance(error_info, str):
            error_code = error_info

    event_type = log.get("event_type")

    # Extract endpoint from http context if available
    http_ctx = log.get("http") or {}
    endpoint = None
    if isinstance(http_ctx, dict):
        endpoint = http_ctx.get("path") or http_ctx.get("route")

    deployment_version = log.get("deployment_version")

    return generate_fingerprint(
        service_name=service_name,
        normalized_text=normalized_text,
        error_code=error_code,
        event_type=event_type,
        endpoint=endpoint,
        deployment_version=deployment_version,
    )
