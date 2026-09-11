"""Celery task definitions for autonomous incident investigation dispatch."""
import asyncio
from typing import Any, Dict
import httpx

from backend.tasks.celery_app import celery_app
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def _run_investigation_async(incident_id: str) -> Dict[str, Any]:
    """Execute investigation by triggering the backend investigation API or direct graph."""
    target_urls = [
        "http://backend:8000/api/v1/investigations/run",
        "http://incident-backend:8000/api/v1/investigations/run",
        "http://localhost:8000/api/v1/investigations/run",
    ]
    payload = {"incident_id": incident_id}

    async with httpx.AsyncClient(timeout=180.0) as client:
        for url in target_urls:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info("Auto-investigation for incident %s completed via %s", incident_id, url)
                    return resp.json()
            except Exception as e:
                logger.debug("Attempt to invoke %s failed: %s", url, e)

    # Fallback to direct LangGraph execution if HTTP endpoint unreachable from worker
    logger.info("Directly executing investigation graph for incident %s", incident_id)
    import uuid
    from sqlalchemy import select
    from backend.agent.graph import run_investigation
    from backend.agent.schemas import InvestigationRunRequest
    from backend.db.session import async_session_factory
    from backend.models.incident import Incident

    req = InvestigationRunRequest(incident_id=incident_id)
    async with async_session_factory() as session:
        inc = (await session.execute(select(Incident).where(Incident.id == uuid.UUID(incident_id)))).scalar_one_or_none()
        if inc:
            req.title = inc.title
            req.primary_service = inc.primary_service
            if inc.representative_log:
                req.error_message = (
                    inc.representative_log.get("message")
                    or inc.representative_log.get("error")
                    or inc.title
                )
                req.error_trace = (
                    inc.representative_log.get("exception")
                    or inc.representative_log.get("traceback")
                    or inc.representative_log.get("stack_trace")
                )

    state = await run_investigation(req)
    return {
        "incident_id": state.get("incident_id"),
        "primary_service": state.get("primary_service"),
        "status": state.get("status"),
        "confidence": state.get("confidence"),
    }


@celery_app.task(
    name="backend.tasks.investigation_tasks.run_incident_investigation_task",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
)
def run_incident_investigation_task(self, incident_id: str) -> Dict[str, Any]:
    """Celery task executing autonomous investigation workflow for a newly created incident."""
    logger.info("Celery task %s auto-investigating incident %s", getattr(self.request, "id", "local"), incident_id)
    try:
        return asyncio.run(_run_investigation_async(incident_id))
    except Exception as exc:
        logger.error("Celery investigation task for incident %s failed: %s", incident_id, exc, exc_info=True)
        raise self.retry(exc=exc)
