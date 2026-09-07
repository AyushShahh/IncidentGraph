"""Continuous Kafka batch consumer for streaming error logs into Celery clustering queue."""
import asyncio
import json
import signal
import time
from typing import List, Dict, Any

from aiokafka import AIOKafkaConsumer
from backend.core.config import settings
from backend.core.logging import get_logger, setup_logging
from backend.tasks.clustering_tasks import process_log_batch_task

logger = get_logger(__name__)


class KafkaBatchClusteringConsumer:
    """Consumes service logs continuously from Kafka, filters actionable errors,

    batches them by count or time interval, and dispatches them to Celery queue.
    """

    def __init__(
        self,
        bootstrap_servers: str = settings.KAFKA_BOOTSTRAP_SERVERS,
        topic: str = settings.KAFKA_LOGS_TOPIC,
        group_id: str = settings.KAFKA_CONSUMER_GROUP,
        batch_size: int = settings.KAFKA_BATCH_SIZE,
        batch_interval: float = settings.KAFKA_BATCH_INTERVAL_SECONDS,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.group_id = group_id
        self.batch_size = batch_size
        self.batch_interval = batch_interval
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False
        self._buffer: List[Dict[str, Any]] = []
        self._last_flush_time = time.monotonic()

    async def start(self) -> None:
        """Initialize consumer and begin consumption loop."""
        logger.info(
            "Starting KafkaBatchClusteringConsumer on topic '%s' (batch_size=%d, interval=%.1fs)...",
            self.topic,
            self.batch_size,
            self.batch_interval,
        )

        self._consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        )

        # Retry loop to connect to Kafka if broker is starting up
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                await self._consumer.start()
                logger.info("Successfully connected to Kafka broker at %s", self.bootstrap_servers)
                break
            except Exception as exc:
                if attempt == max_retries:
                    logger.error("Failed to connect to Kafka broker after %d attempts: %s", max_retries, exc)
                    raise
                logger.warning("Kafka broker connection attempt %d failed: %s. Retrying in 2s...", attempt, exc)
                await asyncio.sleep(2)

        self._running = True
        self._last_flush_time = time.monotonic()

        try:
            await self._consume_loop()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Gracefully stop consumer and flush remaining buffered logs."""
        logger.info("Stopping KafkaBatchClusteringConsumer...")
        self._running = False

        # Flush any remaining logs in buffer
        await self._flush_buffer()

        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
        logger.info("KafkaBatchClusteringConsumer stopped.")

    async def _flush_buffer(self) -> None:
        """Dispatch accumulated log batch to Celery queue."""
        if not self._buffer:
            self._last_flush_time = time.monotonic()
            return

        batch_to_dispatch = list(self._buffer)
        self._buffer.clear()
        self._last_flush_time = time.monotonic()

        logger.info("Flushing batch of %d logs to Celery worker queue...", len(batch_to_dispatch))
        try:
            # Enqueue to Celery via Redis broker
            task = process_log_batch_task.delay(batch_to_dispatch)
            logger.info("Enqueued batch to Celery task ID: %s", task.id)
        except Exception as exc:
            logger.error("Failed to enqueue batch to Celery task: %s", exc, exc_info=True)

    async def _consume_loop(self) -> None:
        """Main continuous polling loop."""
        monitored_levels = settings.monitored_log_levels_set

        while self._running and self._consumer:
            try:
                # Fetch messages with a 1.0 second timeout to permit periodic time-based flushes
                records = await self._consumer.getmany(timeout_ms=1000, max_records=200)

                for tp, messages in records.items():
                    for msg in messages:
                        log_data = msg.value
                        if not isinstance(log_data, dict):
                            continue

                        level = str(log_data.get("log_level") or log_data.get("level") or "").upper()
                        # Only buffer actionable error and warning logs
                        if level in monitored_levels:
                            self._buffer.append(log_data)

                # Check flush conditions: count threshold or time interval exceeded
                now = time.monotonic()
                time_elapsed = now - self._last_flush_time
                count_exceeded = len(self._buffer) >= self.batch_size
                time_exceeded = time_elapsed >= self.batch_interval and len(self._buffer) > 0

                if count_exceeded or time_exceeded:
                    reason = "count" if count_exceeded else "time interval"
                    logger.debug("Triggering batch flush (reason: %s, buffer_len=%d)", reason, len(self._buffer))
                    await self._flush_buffer()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in Kafka consumption loop: %s", exc, exc_info=True)
                await asyncio.sleep(1)


async def main():
    """CLI runner for standalone clustering consumer service."""
    setup_logging()
    consumer = KafkaBatchClusteringConsumer()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(consumer.stop()))
        except NotImplementedError:
            # Windows signal handlers may not support add_signal_handler
            pass

    await consumer.start()


if __name__ == "__main__":
    asyncio.run(main())
