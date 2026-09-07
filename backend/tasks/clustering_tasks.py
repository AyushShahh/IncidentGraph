"""Celery task definitions for asynchronous log batch clustering."""
import asyncio
from typing import List, Dict, Any

from backend.tasks.celery_app import celery_app
from backend.tasks.clustering_pipeline import IncidentClusteringPipeline
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def _run_batch_pipeline(raw_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Execute pipeline and ensure client connections on this event loop are disposed."""
    from backend.db.session import engine
    from backend.redis.client import close_redis_client
    from backend.qdrant.client import close_qdrant_client

    try:
        pipeline = IncidentClusteringPipeline()
        return await pipeline.process_batch(raw_logs)
    finally:
        await engine.dispose()
        await close_redis_client()
        await close_qdrant_client()


@celery_app.task(
    name="backend.tasks.clustering_tasks.process_log_batch_task",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
)
def process_log_batch_task(self, raw_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Celery task executing the IncidentClusteringPipeline asynchronously on a batch of logs."""
    logger.info("Celery task %s received batch of %d logs", self.request.id, len(raw_logs))
    try:
        return asyncio.run(_run_batch_pipeline(raw_logs))
    except Exception as exc:
        logger.error("Celery task %s encountered error: %s", self.request.id, exc, exc_info=True)
        raise self.retry(exc=exc)
