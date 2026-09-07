"""Modular log text normalizer for stripping dynamic variables before fingerprinting."""
import re
from typing import Optional


class LogNormalizer:
    """Normalizes log messages and error texts by masking dynamic values.

    Masks volatile fields such as UUIDs, IP addresses, memory addresses,
    timestamps, prefixed entity IDs, trace IDs, quoted literals, and standalone
    numbers to ensure identical structural errors produce identical normalized representations.
    Completely domain-agnostic with zero hardcoded service names or entity prefixes.
    """

    # Pre-compiled regex patterns ordered for optimal substitution
    _UUID_REGEX = re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    )
    _HEX_ADDR_REGEX = re.compile(r"0x[0-9a-fA-F]+")
    _IP_ADDR_REGEX = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{1,5})?\b")
    _TIMESTAMP_REGEX = re.compile(
        r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
    )

    # Standalone Trace / Hash IDs (16 to 64 lowercase hex characters)
    _TRACE_ID_REGEX = re.compile(r"\b[a-f0-9]{16,64}\b")

    # Latency / Duration patterns (e.g. 154.23ms, 2.5s)
    _DURATION_REGEX = re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:ms|s|µs|ns|seconds?|milliseconds?)\b", re.IGNORECASE
    )

    # Stack trace line numbers and file paths
    _TRACE_FILE_REGEX = re.compile(r'File "([^"]+)", line \d+')
    _LINE_NUM_REGEX = re.compile(r"\bline \d+\b", re.IGNORECASE)

    # Generic Prefixed Entity IDs (e.g. ord-123, tx-456, SKU-100, user-std-9713, pod-88)
    # Generic regex extracting prefix \1 and replacing dynamic suffix with <ID>
    _GENERIC_ID_REGEX = re.compile(
        r"\b([a-zA-Z]{2,12})-(?:[a-zA-Z0-9_-]*\d+[a-zA-Z0-9_-]*|[A-Z0-9_-]{2,})\b"
    )

    # Quoted dynamic literals in error messages (e.g. 'GBP', 'PLATINUM', 'SKU-100')
    # Excludes already masked tokens containing < and > (e.g. "<FILE>")
    _QUOTED_LITERAL_REGEX = re.compile(r"['\"][^'\"\n<>]{1,64}['\"]")

    # Standalone numbers (excluding standard 3-digit HTTP status codes 100-599)
    _NUM_REGEX = re.compile(r"\b(?!(?:[1-5]\d\d)\b)\d+(?:\.\d+)?\b")

    # Extra whitespace
    _WHITESPACE_REGEX = re.compile(r"\s+")

    @classmethod
    def normalize(cls, text: Optional[str]) -> str:
        """Strip dynamic variables from an input string and collapse whitespace."""
        if not text:
            return ""

        # 1. Timestamps
        s = cls._TIMESTAMP_REGEX.sub("<TIMESTAMP>", text)

        # 2. UUIDs
        s = cls._UUID_REGEX.sub("<UUID>", s)

        # 3. Stack trace file paths and line numbers
        s = cls._TRACE_FILE_REGEX.sub(r'File "<FILE>", line <NUM>', s)
        s = cls._LINE_NUM_REGEX.sub("line <NUM>", s)

        # 4. Memory addresses
        s = cls._HEX_ADDR_REGEX.sub("<HEX>", s)

        # 5. IP Addresses
        s = cls._IP_ADDR_REGEX.sub("<IP>", s)

        # 6. Trace / Hash IDs
        s = cls._TRACE_ID_REGEX.sub("<TRACE_ID>", s)

        # 7. Latencies / Durations
        s = cls._DURATION_REGEX.sub("<DURATION>", s)

        # 8. Generic Prefixed Entity IDs (ord-<ID>, tx-<ID>, SKU-<ID>, user-<ID>, etc.)
        s = cls._GENERIC_ID_REGEX.sub(r"\1-<ID>", s)

        # 9. Quoted Dynamic Literals (e.g. 'GBP', 'PLATINUM', 'SKU-100')
        s = cls._QUOTED_LITERAL_REGEX.sub("'<LITERAL>'", s)

        # 10. Standalone Numbers (preserving HTTP status codes 100-599)
        s = cls._NUM_REGEX.sub("<NUM>", s)

        # 11. Whitespace collapsing
        s = cls._WHITESPACE_REGEX.sub(" ", s).strip()

        return s

    @classmethod
    def extract_and_normalize(cls, log: dict) -> str:
        """Extract the most relevant error text from a structured log and normalize it."""
        # Prefer structured error message or exception details
        error_info = log.get("error") or {}
        error_msg = log.get("error_code") or ""
        if not error_msg:
            if isinstance(error_info, dict):
                error_msg = (
                    error_info.get("message")
                    or error_info.get("error_code")
                    or error_info.get("type")
                    or ""
                )
            elif isinstance(error_info, str):
                error_msg = error_info
        if not error_msg and log.get("exception"):
            error_msg = str(log.get("exception"))[:100]

        message = log.get("message") or ""
        event_type = log.get("event_type") or ""

        # Combine message and error_msg if distinct
        parts = []
        if message:
            parts.append(message)
        if error_msg and error_msg not in message:
            parts.append(error_msg)
        if not parts and event_type:
            parts.append(event_type)

        raw_text = " | ".join(parts) if parts else "Unknown error event"
        return cls.normalize(raw_text)


# Convenient module-level singleton instance
normalizer = LogNormalizer()
