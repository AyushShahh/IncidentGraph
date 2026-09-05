"""Common helper utilities for time, hashing, and IDs."""
import uuid
from datetime import datetime, timezone


def generate_id() -> str:
    """Generate a UUID4 string."""
    return str(uuid.uuid4())


def get_utc_now() -> datetime:
    """Get current UTC timezone-aware datetime."""
    return datetime.now(timezone.utc)


def sanitize_log_message(message: str) -> str:
    """Strip sensitive tokens or secrets from logs."""
    # TODO: Implement regex mask for API keys, bearer tokens, and PII
    return message.strip()
