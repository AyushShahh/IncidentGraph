"""Global constants for topics, event types, and incident lifecycles."""
from enum import StrEnum


class KafkaTopics(StrEnum):
    SERVICE_LOGS = "service-logs"
    INCIDENT_EVENTS = "incident-events"
    REMEDIATION_ACTIONS = "remediation-actions"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class IncidentStatus(StrEnum):
    TRIGGERED = "TRIGGERED"
    INVESTIGATING = "INVESTIGATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class IncidentSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# Qdrant collection names
QDRANT_INCIDENT_COLLECTION = "incident_resolutions"
QDRANT_CODE_COLLECTION = "repository_code"
