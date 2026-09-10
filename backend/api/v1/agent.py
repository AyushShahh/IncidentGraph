"""REST API endpoints for the Autonomous Incident Investigation Agent."""
import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.graph import run_investigation
from backend.agent.memory.execution_memory import execution_memory
from backend.agent.memory.incident_memory import incident_memory
from backend.agent.schemas import (
    InvestigationApprovalRequest,
    InvestigationRunRequest,
)
from backend.core.logging import get_logger
from backend.db.session import get_db_session
from backend.models.incident import Incident, IncidentResolution

logger = get_logger(__name__)

router = APIRouter()


@router.post("/run", summary="Trigger autonomous incident investigation")
async def trigger_investigation(
    request: InvestigationRunRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Execute LangGraph autonomous investigation workflow for an incident."""
    # If incident_id provided, verify or fetch details from PostgreSQL
    if request.incident_id:
        try:
            inc_uuid = uuid.UUID(request.incident_id)
            stmt = select(Incident).where(Incident.id == inc_uuid)
            res = await session.execute(stmt)
            inc = res.scalar_one_or_none()
            if inc:
                if not request.title:
                    request.title = inc.title
                if not request.primary_service:
                    request.primary_service = inc.primary_service
                if not request.error_message and inc.representative_log:
                    request.error_message = (
                        inc.representative_log.get("message")
                        or inc.representative_log.get("error")
                        or inc.summary
                        or inc.title
                    )
                if not request.error_trace and inc.representative_log:
                    request.error_trace = (
                        inc.representative_log.get("traceback")
                        or inc.representative_log.get("stack_trace")
                        or inc.representative_log.get("trace")
                    )
                # If still missing error_message, check first candidate
                if not request.error_message and inc.candidates:
                    first_cand = inc.candidates[0]
                    request.error_message = first_cand.normalized_text
                    if not request.error_trace and first_cand.representative_log:
                        request.error_trace = (
                            first_cand.representative_log.get("traceback")
                            or first_cand.representative_log.get("stack_trace")
                        )
        except ValueError:
            pass

    if not request.primary_service:
        raise HTTPException(
            status_code=422,
            detail="Could not resolve 'primary_service'. Please provide it or a valid 'incident_id'.",
        )
    if not request.error_message:
        request.error_message = request.title or f"Incident in {request.primary_service}"

    final_state = await run_investigation(request)

    return {
        "incident_id": final_state.get("incident_id"),
        "primary_service": final_state.get("primary_service"),
        "status": final_state.get("status"),
        "confidence": final_state.get("confidence"),
        "approval_status": final_state.get("approval_status"),
        "cached_solution_found": final_state.get("cached_solution_found", False),
        "reused_incident_id": final_state.get("reused_incident_id"),
        "iterations": final_state.get("iteration_count", 0),
        "tokens_used": final_state.get("tokens_used", 0),
        "final_report": final_state.get("final_report"),
        "hypothesis": final_state.get("hypothesis"),
    }


@router.get("/{incident_id}", summary="Get investigation report and status by incident ID")
async def get_investigation(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve the latest investigation report, resolution, and audit status."""
    # 1. Check Redis execution memory first
    cached_state = await execution_memory.load_checkpoint(incident_id)
    if cached_state:
        return {
            "source": "execution_memory",
            "incident_id": incident_id,
            "status": cached_state.get("status"),
            "approval_status": cached_state.get("approval_status"),
            "confidence": cached_state.get("confidence"),
            "iterations": cached_state.get("iteration_count", 0),
            "final_report": cached_state.get("final_report"),
            "evidence": cached_state.get("evidence", []),
            "hypothesis": cached_state.get("hypothesis"),
            "tokens_used": cached_state.get("tokens_used", 0),
        }

    # 2. Fall back to PostgreSQL resolution record
    try:
        inc_uuid = uuid.UUID(incident_id)
        stmt = select(IncidentResolution).where(IncidentResolution.incident_id == inc_uuid)
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        if record:
            return {
                "source": "incident_memory",
                "incident_id": incident_id,
                "status": record.status,
                "approval_status": "APPROVED" if record.human_approval else ("REJECTED" if record.human_approval is False else "PENDING"),
                "confidence": record.confidence,
                "final_report": record.to_dict(),
            }
    except ValueError:
        pass

    raise HTTPException(status_code=404, detail=f"No investigation found for incident '{incident_id}'.")


@router.post("/{incident_id}/approve", summary="Submit human approval or rejection on investigation")
async def approve_investigation(
    incident_id: str,
    payload: InvestigationApprovalRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Approve or reject an investigated incident resolution, committing it to memory."""
    # Load state from Redis or database
    cached_state = await execution_memory.load_checkpoint(incident_id)
    rep_dict = cached_state.get("final_report", {}) if cached_state else {}

    # If not in Redis, check DB
    if not rep_dict:
        try:
            inc_uuid = uuid.UUID(incident_id)
            stmt = select(IncidentResolution).where(IncidentResolution.incident_id == inc_uuid)
            res = await session.execute(stmt)
            existing_rec = res.scalar_one_or_none()
            if existing_rec:
                rep_dict = existing_rec.to_dict()
        except ValueError:
            pass

    if not rep_dict:
        raise HTTPException(
            status_code=404,
            detail=f"Cannot approve investigation '{incident_id}': no report found.",
        )

    # Commit resolution to PostgreSQL and Qdrant
    record = await incident_memory.store_resolution(
        session=session,
        incident_id=incident_id,
        resolution_data=rep_dict,
        approved=payload.approved,
        reviewer_feedback=payload.reviewer_feedback,
    )

    # Update checkpoint in Redis
    if cached_state:
        cached_state["approval_status"] = "APPROVED" if payload.approved else "REJECTED"
        cached_state["status"] = "RESOLVED" if payload.approved else "REJECTED"
        await execution_memory.save_checkpoint(incident_id, cached_state)

    return {
        "message": f"Investigation resolution {'APPROVED' if payload.approved else 'REJECTED'} successfully.",
        "incident_id": incident_id,
        "status": record.status,
        "human_approval": record.human_approval,
        "reviewer_feedback": record.reviewer_feedback,
        "resolution": record.to_dict(),
    }
