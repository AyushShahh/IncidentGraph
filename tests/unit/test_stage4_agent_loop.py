"""Unit tests for the autonomous Stage 4 LangGraph investigation loop."""
import uuid
import pytest
from unittest.mock import AsyncMock, patch

from backend.agent.graph import run_investigation
from backend.agent.providers.factory import set_global_provider_override
from backend.agent.providers.mock import MockLLMProvider
from backend.agent.schemas import InvestigationRunRequest


@pytest.fixture(autouse=True)
def use_mock_llm():
    """Ensure all tests in this file use deterministic MockLLMProvider."""
    provider = MockLLMProvider()
    set_global_provider_override(provider)
    yield
    set_global_provider_override(None)


@pytest.mark.asyncio
async def test_full_investigation_loop_awaiting_approval():
    """Test standard investigation workflow terminating at AWAITING_APPROVAL."""
    inc_id = f"test-inc-{uuid.uuid4().hex[:8]}"
    req = InvestigationRunRequest(
        incident_id=inc_id,
        primary_service="inventory",
        title="High error rate in stock allocation",
        error_message="DatabaseLockTimeout: deadlock detected in inventory allocation",
        error_trace="File 'inventory/service.py', line 45, in allocate_stock\nraise DatabaseLockTimeout('deadlock')",
        max_iterations=3,
        auto_approve=False,
    )

    with patch("backend.agent.graph.incident_memory.search_similar_resolution", new_callable=AsyncMock) as mock_search, \
         patch("backend.agent.graph.incident_memory.store_resolution", new_callable=AsyncMock) as mock_store:
        mock_search.return_value = None  # Cache miss

        final_state = await run_investigation(req)

        assert final_state["incident_id"] == inc_id
        assert final_state["status"] == "AWAITING_APPROVAL"
        assert final_state["approval_status"] == "AWAITING_APPROVAL"
        assert final_state["cached_solution_found"] is False
        assert final_state["iteration_count"] >= 1

        # Check evidence gathering
        assert len(final_state["evidence"]) >= 1
        assert any(ev.get("source_tool") in ("read_lines", "trace_parser", "search_code") for ev in final_state["evidence"])

        # Check hypothesis
        assert final_state.get("hypothesis") is not None
        assert final_state["confidence"] >= 0.85

        # Check final report
        assert final_state.get("final_report") is not None
        rep = final_state["final_report"]
        assert rep["primary_service"] == "inventory"
        assert rep["root_cause"] != ""
        assert rep["suggested_fix"] != ""


@pytest.mark.asyncio
async def test_investigation_cache_hit_shortcut():
    """Test memory lookup cache hit immediately shortcuts the investigation with 0 LLM loops."""
    inc_id = f"test-inc-{uuid.uuid4().hex[:8]}"
    req = InvestigationRunRequest(
        incident_id=inc_id,
        primary_service="orders",
        title="Order creation 500 error",
        error_message="KeyError: missing customer tier",
        max_iterations=3,
    )

    prior_resolution = {
        "incident_id": "resolved-prev-001",
        "service": "orders",
        "root_cause": "Unchecked KeyError when customer tier missing in JWT token",
        "suggested_fix": "Use .get('tier', 'standard') with default fallback",
        "resolution_summary": "Handled missing JWT claim gracefully",
        "confidence": 0.98,
        "score": 0.95,
    }

    with patch("backend.agent.graph.incident_memory.search_similar_resolution", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = prior_resolution

        final_state = await run_investigation(req)

        assert final_state["incident_id"] == inc_id
        assert final_state["cached_solution_found"] is True
        assert final_state["reused_incident_id"] == "resolved-prev-001"
        assert final_state["status"] == "RESOLVED"
        assert final_state["approval_status"] == "APPROVED"
        assert final_state["iteration_count"] == 0  # Bypassed LLM loop entirely
        assert final_state["confidence"] == 0.98


@pytest.mark.asyncio
async def test_investigation_auto_approve():
    """Test that auto_approve=True routes through memory_writer to status=RESOLVED."""
    inc_id = f"test-inc-{uuid.uuid4().hex[:8]}"
    req = InvestigationRunRequest(
        incident_id=inc_id,
        primary_service="inventory",
        title="Lock contention",
        error_message="DatabaseLockTimeout",
        auto_approve=True,
    )

    with patch("backend.agent.graph.incident_memory.search_similar_resolution", new_callable=AsyncMock) as mock_search, \
         patch("backend.agent.graph.incident_memory.store_resolution", new_callable=AsyncMock) as mock_store:
        mock_search.return_value = None

        final_state = await run_investigation(req)

        assert final_state["incident_id"] == inc_id
        assert final_state["status"] == "RESOLVED"
        assert final_state["approval_status"] == "APPROVED"
        mock_store.assert_called_once()


@pytest.mark.asyncio
async def test_investigation_max_iterations_cap():
    """Verify that loop strictly terminates when max_iterations is reached even if confidence is low."""
    inc_id = f"test-inc-{uuid.uuid4().hex[:8]}"
    req = InvestigationRunRequest(
        incident_id=inc_id,
        primary_service="inventory",
        title="Flaky error",
        error_message="Unknown timeout",
        max_iterations=1,
        confidence_threshold=0.99,  # High threshold won't be met
    )

    with patch("backend.agent.graph.incident_memory.search_similar_resolution", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = None

        final_state = await run_investigation(req)

        assert final_state["iteration_count"] == 1
        assert final_state["phase"] in ("reviewer", "human_approval", "complete")
