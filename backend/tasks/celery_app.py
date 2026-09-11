"""Celery application configuration for asynchronous incident processing queues."""
from celery import Celery
from backend.core.config import settings

celery_app = Celery(
    "ai_incident_intelligence",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "backend.tasks.clustering_tasks",
        "backend.tasks.investigation_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per batch
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
)
