"""Unit tests for Stage 4 REST API endpoints (/api/v1/investigations)."""
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.router import api_router
from backend.agent.memory.execution_memory import execution_memory
from backend.agent.providers.factory import set_global_provider_override
from backend.agent.providers.mock import MockLLMProvider


def get_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    return app


@pytest.fixture(autouse=True)
def use_mock_llm():
    provider = MockLLMProvider()
    set_global_provider_override(provider)
    yield
    set_global_provider_override(None)


@pytest.mark.asyncio
async def test_api_trigger_investigation():
    """POST /api/v1/investigations/run should execute workflow and return summary."""
    app = get_test_app()
    transport = ASGITransport(app=app)
    inc_id = f"api-inc-{uuid.uuid4().hex[:8]}"

    with patch("backend.agent.graph.incident_memory.search_similar_resolution", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = None

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/investigations/run",
                json={
                    "incident_id": inc_id,
                    "primary_service": "inventory",
                    "title": "Deadlock in inventory allocation",
                    "error_message": "DatabaseLockTimeout: deadlock detected",
                    "max_iterations": 2,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["incident_id"] == inc_id
            assert data["primary_service"] == "inventory"
            assert data["status"] in ("AWAITING_APPROVAL", "INVESTIGATING")
            assert data["confidence"] >= 0.85
            assert "final_report" in data
            assert data["final_report"]["root_cause"] != ""


@pytest.mark.asyncio
async def test_api_get_investigation_from_execution_memory():
    """GET /api/v1/investigations/{incident_id} retrieves cached checkpoint."""
    app = get_test_app()
    transport = ASGITransport(app=app)
    inc_id = f"api-inc-{uuid.uuid4().hex[:8]}"

    cached_state = {
        "incident_id": inc_id,
        "status": "AWAITING_APPROVAL",
        "approval_status": "AWAITING_APPROVAL",
        "confidence": 0.91,
        "iteration_count": 1,
        "final_report": {
            "root_cause": "Deadlock ordering",
            "suggested_fix": "Sort keys",
        },
        "evidence": [],
        "hypothesis": {"root_cause_statement": "Deadlock ordering"},
    }
    await execution_memory.save_checkpoint(inc_id, cached_state)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/investigations/{inc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "execution_memory"
        assert data["incident_id"] == inc_id
        assert data["confidence"] == 0.91
        assert data["final_report"]["root_cause"] == "Deadlock ordering"


@pytest.mark.asyncio
async def test_api_get_investigation_not_found():
    """GET /api/v1/investigations/{incident_id} returns 404 when absent."""
    app = get_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/investigations/non-existent-uuid-{uuid.uuid4().hex[:6]}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_approve_investigation():
    """POST /api/v1/investigations/{incident_id}/approve commits resolution."""
    app = get_test_app()
    transport = ASGITransport(app=app)
    inc_id = str(uuid.uuid4())

    cached_state = {
        "incident_id": inc_id,
        "primary_service": "inventory",
        "status": "AWAITING_APPROVAL",
        "approval_status": "AWAITING_APPROVAL",
        "final_report": {
            "root_cause": "Deadlock in allocation",
            "suggested_fix": "Acquire locks in sorted SKU order",
            "confidence": 0.92,
        },
    }
    await execution_memory.save_checkpoint(inc_id, cached_state)

    with patch("backend.api.v1.agent.incident_memory.store_resolution", new_callable=AsyncMock) as mock_store:
        mock_rec = MagicMock()
        mock_rec.status = "APPROVED"
        mock_rec.human_approval = True
        mock_rec.reviewer_feedback = "Approved by SRE"
        mock_rec.to_dict.return_value = {"id": str(uuid.uuid4()), "status": "APPROVED"}
        mock_store.return_value = mock_rec

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/investigations/{inc_id}/approve",
                json={
                    "approved": True,
                    "reviewer_feedback": "Approved by SRE",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "APPROVED" in data["message"]
            assert data["status"] == "APPROVED"
            assert data["human_approval"] is True
            mock_store.assert_called_once()
