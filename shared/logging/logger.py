"""Structured JSON event logger with Kafka publishing."""
import asyncio
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Optional, Union
from shared.schemas.log_event import LogEventSchema, _default_instance_id
from shared.kafka.producer import get_shared_kafka_producer, KafkaLogProducer
from shared.logging.context import (
    get_request_id,
    get_trace_id,
    get_session_id,
    get_upstream_service,
)


class StructuredEventLogger:
    """Emits structured JSON logs conforming to LogEventSchema and streams them to Kafka."""

    def __init__(
        self,
        service_name: str,
        instance_id: Optional[str] = None,
        deployment_version: Optional[str] = None,
        environment: Optional[str] = None,
        kafka_producer: Optional[KafkaLogProducer] = None,
    ) -> None:
        self.service_name = service_name
        self.instance_id = instance_id or _default_instance_id()
        self.deployment_version = (
            deployment_version
            or os.getenv("DEPLOYMENT_VERSION", "v1.0.0")
        )
        self.environment = (
            environment
            or os.getenv("ENVIRONMENT", "development")
        )
        self._kafka_producer = kafka_producer

    @property
    def kafka_producer(self) -> KafkaLogProducer:
        if self._kafka_producer is None:
            self._kafka_producer = get_shared_kafka_producer()
        return self._kafka_producer

    def _build_log_event(
        self,
        level: str,
        message: str,
        event_type: str = "application_event",
        exception: Optional[Union[str, Exception]] = None,
        downstream_service: Optional[str] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> LogEventSchema:
        """Construct a validated LogEventSchema record with ambient tracing context."""
        exc_str: Optional[str] = None
        if isinstance(exception, Exception):
            exc_str = "".join(
                traceback.format_exception(type(exception), exception, exception.__traceback__)
            )
        elif isinstance(exception, str):
            exc_str = exception

        return LogEventSchema(
            timestamp=datetime.now(timezone.utc),
            service_name=self.service_name,
            instance_id=self.instance_id,
            request_id=get_request_id(),
            trace_id=get_trace_id(),
            session_id=get_session_id(),
            log_level=level.upper(),
            event_type=event_type,
            message=message,
            exception=exc_str,
            upstream_service=get_upstream_service(),
            downstream_service=downstream_service,
            deployment_version=self.deployment_version,
            environment=self.environment,
            attributes=attributes or {},
        )

    def _emit(self, event: LogEventSchema) -> None:
        """Write JSON log to stdout and dispatch to Kafka."""
        payload = json.loads(event.model_dump_json())
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

        # Dispatch to Kafka in current loop if available
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                producer = self.kafka_producer
                if producer.is_started:
                    loop.create_task(producer.send_log(event))
        except RuntimeError:
            pass

    def log_event(
        self,
        level: str,
        message: str,
        event_type: str = "application_event",
        exception: Optional[Union[str, Exception]] = None,
        downstream_service: Optional[str] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> LogEventSchema:
        """Publish an explicit log event."""
        event = self._build_log_event(
            level=level,
            message=message,
            event_type=event_type,
            exception=exception,
            downstream_service=downstream_service,
            attributes=attributes,
        )
        self._emit(event)
        return event

    def info(self, message: str, **kwargs: Any) -> LogEventSchema:
        return self.log_event("INFO", message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> LogEventSchema:
        return self.log_event("DEBUG", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> LogEventSchema:
        return self.log_event("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> LogEventSchema:
        return self.log_event("ERROR", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> LogEventSchema:
        return self.log_event("CRITICAL", message, **kwargs)


# Registry of service loggers
_service_loggers: dict[str, StructuredEventLogger] = {}


def get_service_logger(service_name: str) -> StructuredEventLogger:
    """Factory for service loggers."""
    if service_name not in _service_loggers:
        _service_loggers[service_name] = StructuredEventLogger(service_name=service_name)
    return _service_loggers[service_name]
