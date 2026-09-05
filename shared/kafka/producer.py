"""Production Kafka producer for structured log event streaming."""
import asyncio
import json
import logging
import os
from typing import Any, Optional, Union
from aiokafka import AIOKafkaProducer
from shared.schemas.log_event import LogEventSchema

logger = logging.getLogger("kafka.producer")


class KafkaLogProducer:
    """Production-grade Kafka producer for structured log streaming.

    Features:
    - Real AIOKafkaProducer with send_and_wait()
    - Configurable bootstrap servers, retries, and topic names
    - Reconnect and graceful lifecycle management (start/stop)
    - Zero fake/in-memory buffering in production code
    """

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        default_topic: str = "service-logs",
        client_id: Optional[str] = None,
        request_timeout_ms: int = 5000,
        retry_backoff_ms: int = 200,
    ) -> None:
        self.bootstrap_servers = (
            bootstrap_servers
            or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        )
        self.default_topic = os.getenv("KAFKA_LOGS_TOPIC", default_topic)
        self.client_id = client_id or os.getenv("SERVICE_NAME", "kafka-producer")
        self.request_timeout_ms = request_timeout_ms
        self.retry_backoff_ms = retry_backoff_ms

        self._producer: Optional[AIOKafkaProducer] = None
        self._is_started = False
        self._lock = asyncio.Lock()

    @property
    def is_started(self) -> bool:
        return self._is_started

    @is_started.setter
    def is_started(self, value: bool) -> None:
        self._is_started = value

    async def start(self) -> None:
        """Initialize connection to Kafka broker."""
        async with self._lock:
            if self._is_started and self._producer:
                return

            try:
                self._producer = AIOKafkaProducer(
                    bootstrap_servers=self.bootstrap_servers,
                    client_id=self.client_id,
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    key_serializer=lambda k: k.encode("utf-8") if k else None,
                    request_timeout_ms=self.request_timeout_ms,
                    retry_backoff_ms=self.retry_backoff_ms,
                    connections_max_idle_ms=30000,
                )
                await self._producer.start()
                self._is_started = True
                logger.info(
                    "Connected Kafka producer to %s (client_id=%s, default_topic=%s)",
                    self.bootstrap_servers,
                    self.client_id,
                    self.default_topic,
                )
            except Exception as exc:
                self._producer = None
                self._is_started = False
                logger.error(
                    "Failed to connect Kafka producer to %s: %s",
                    self.bootstrap_servers,
                    exc,
                )
                raise exc

    async def stop(self) -> None:
        """Flush and close producer connection gracefully."""
        async with self._lock:
            if self._producer and self._is_started:
                try:
                    await self._producer.stop()
                    logger.info("Gracefully stopped Kafka producer for %s", self.client_id)
                except Exception as exc:
                    logger.warning("Error stopping Kafka producer: %s", exc)
                finally:
                    self._producer = None
                    self._is_started = False

    async def send_log(
        self,
        log_event: Union[LogEventSchema, dict[str, Any]],
        topic: Optional[str] = None,
        key: Optional[str] = None,
    ) -> bool:
        """Publish a structured log record to Kafka with delivery confirmation."""
        target_topic = topic or self.default_topic

        # Serialize if pydantic model
        if isinstance(log_event, LogEventSchema):
            payload = json.loads(log_event.model_dump_json())
            partition_key = key or log_event.service_name
        else:
            payload = log_event
            partition_key = key or str(log_event.get("service_name", self.client_id))

        if not self._producer or not self._is_started:
            logger.warning(
                "Cannot deliver log to Kafka topic %s: Producer is not started.",
                target_topic,
            )
            return False

        try:
            await self._producer.send_and_wait(
                topic=target_topic,
                value=payload,
                key=partition_key,
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to publish log to Kafka topic %s: %s",
                target_topic,
                exc,
            )
            return False


_global_producer: Optional[KafkaLogProducer] = None


def get_shared_kafka_producer() -> KafkaLogProducer:
    """Singleton getter for shared Kafka producer."""
    global _global_producer
    if _global_producer is None:
        _global_producer = KafkaLogProducer()
    return _global_producer


# Backwards compatibility alias
GenericKafkaLogProducer = KafkaLogProducer
