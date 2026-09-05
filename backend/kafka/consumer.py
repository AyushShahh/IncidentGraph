"""Kafka message consumer service."""
import json
from typing import AsyncGenerator, Any
from aiokafka import AIOKafkaConsumer
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class KafkaConsumerService:
    """Service wrapper for subscribing to topics and consuming incoming log events."""

    def __init__(
        self,
        topic: str = settings.KAFKA_LOGS_TOPIC,
        bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id: str = settings.KAFKA_CONSUMER_GROUP,
    ) -> None:
        self.topic = topic
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self._consumer: AIOKafkaConsumer | None = None

    async def start(self) -> None:
        """Initialize and start consumer loop."""
        logger.info("Connecting Kafka consumer to %s on topic %s", self.bootstrap_servers, self.topic)
        self._consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        )
        await self._consumer.start()

    async def stop(self) -> None:
        """Close Kafka consumer."""
        if self._consumer:
            logger.info("Stopping Kafka consumer...")
            await self._consumer.stop()
            self._consumer = None

    async def consume_messages(self) -> AsyncGenerator[dict[str, Any], None]:
        """Yield consumed message records."""
        # TODO: Implement batching, backpressure control, and offset commit confirmation
        if not self._consumer:
            raise RuntimeError("Consumer is not running")
        async for msg in self._consumer:
            yield msg.value
