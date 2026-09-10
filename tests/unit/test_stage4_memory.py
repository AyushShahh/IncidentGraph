"""Unit tests for Stage 4 Memory Layer (Execution Memory and Incident Memory)."""
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agent.memory.execution_memory import ExecutionMemory
from backend.agent.memory.incident_memory import IncidentMemory
from backend.models.incident import Incident, IncidentResolution


@pytest.mark.asyncio
async def test_execution_memory_lifecycle():
    """Test checkpoint save/load, visited tracking, and clear on ExecutionMemory."""
    mem = ExecutionMemory(ttl_seconds=60)
    inc_id = f"test-inc-{uuid.uuid4().hex[:8]}"

    # Save checkpoint
    state = {
        "incident_id": inc_id,
        "iteration": 1,
        "status": "INVESTIGATING",
        "evidence": [{"source_tool": "test", "finding_summary": "found something"}],
    }
    await mem.save_checkpoint(inc_id, state)

    # Load checkpoint
    loaded = await mem.load_checkpoint(inc_id)
    assert loaded is not None
    assert loaded["incident_id"] == inc_id
    assert loaded["iteration"] == 1
    assert len(loaded["evidence"]) == 1

    # Visited tracking
    await mem.add_visited(inc_id, "files", "services/order.py")
    await mem.add_visited(inc_id, "files", "services/inventory.py")
    await mem.add_visited(inc_id, "symbols", "reserve_stock")

    visited_files = await mem.get_visited(inc_id, "files")
    assert "services/order.py" in visited_files
    assert "services/inventory.py" in visited_files

    visited_symbols = await mem.get_visited(inc_id, "symbols")
    assert "reserve_stock" in visited_symbols

    # Clear memory
    await mem.clear(inc_id)
    assert await mem.load_checkpoint(inc_id) is None
    cleared_files = await mem.get_visited(inc_id, "files")
    assert len(cleared_files) == 0


@pytest.mark.asyncio
async def test_incident_memory_search_not_found():
    """When Qdrant returns no hits, search_similar_resolution returns None."""
    mem = IncidentMemory()

    mock_qdrant = AsyncMock()
    mock_qdrant.collection_exists.return_value = True
    mock_qdrant.query_points.return_value = MagicMock(points=[])

    mock_emb = AsyncMock()
    mock_emb.embed_text.return_value = [0.1] * 384

    with patch("backend.agent.memory.incident_memory.get_qdrant_client", return_value=mock_qdrant), \
         patch("backend.agent.memory.incident_memory.get_embedding_provider", return_value=mock_emb):
        res = await mem.search_similar_resolution("deadlock detected", service="inventory")
        assert res is None


@pytest.mark.asyncio
async def test_incident_memory_search_found():
    """When Qdrant returns a high-similarity point, return resolution details."""
    mem = IncidentMemory()

    mock_hit = MagicMock()
    mock_hit.score = 0.94
    mock_hit.payload = {
        "incident_id": "prev-123",
        "service": "inventory",
        "root_cause": "Deadlock in inventory reservation lock ordering",
        "suggested_fix": "Sort SKU IDs before acquiring row locks",
        "resolution_summary": "Resolved by ordering lock acquisition",
        "confidence": 0.95,
    }

    mock_qdrant = AsyncMock()
    mock_qdrant.collection_exists.return_value = True
    mock_qdrant.query_points.return_value = MagicMock(points=[mock_hit])

    mock_emb = AsyncMock()
    mock_emb.embed_text.return_value = [0.1] * 384

    with patch("backend.agent.memory.incident_memory.get_qdrant_client", return_value=mock_qdrant), \
         patch("backend.agent.memory.incident_memory.get_embedding_provider", return_value=mock_emb):
        res = await mem.search_similar_resolution("deadlock in allocation", service="inventory", threshold=0.88)
        assert res is not None
        assert res["incident_id"] == "prev-123"
        assert "Deadlock in inventory" in res["root_cause"]
        assert res["score"] == 0.94


@pytest.mark.asyncio
async def test_incident_memory_store_resolution_approval():
    """Test storing approved resolution and indexing into Qdrant."""
    mem = IncidentMemory()

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    
    # First execute: parent Incident query (returns existing Incident)
    # Second execute: IncidentResolution query (returns None for new record)
    mock_parent = MagicMock(spec=Incident, primary_service="inventory", status="ACTIVE")
    res_parent = MagicMock()
    res_parent.scalar_one_or_none.return_value = mock_parent
    
    res_resol = MagicMock()
    res_resol.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [res_parent, res_resol]

    inc_id = str(uuid.uuid4())
    res_data = {
        "root_cause": "Database lock timeout",
        "resolution_summary": "Add consistent ordering",
        "suggested_fix": "Fix SQL query ORDER BY",
        "confidence": 0.92,
        "affected_services": ["inventory"],
        "inspected_files": ["services/inventory.py"],
        "inspected_symbols": ["reserve_stock"],
    }

    with patch.object(mem, "_index_resolution_in_qdrant", new_callable=AsyncMock) as mock_index:
        record = await mem.store_resolution(
            session=mock_session,
            incident_id=inc_id,
            resolution_data=res_data,
            approved=True,
            reviewer_feedback="Looks solid"
        )
        assert record.status == "APPROVED"
        assert record.human_approval is True
        assert record.reviewer_feedback == "Looks solid"
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_index.assert_called_once()


@pytest.mark.asyncio
async def test_incident_memory_store_resolution_rejection():
    """Test storing rejected resolution skips Qdrant indexing."""
    mem = IncidentMemory()

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    
    mock_parent = MagicMock(spec=Incident, primary_service="inventory", status="ACTIVE")
    res_parent = MagicMock()
    res_parent.scalar_one_or_none.return_value = mock_parent
    
    res_resol = MagicMock()
    res_resol.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [res_parent, res_resol]

    inc_id = str(uuid.uuid4())
    res_data = {
        "root_cause": "Bad guess",
        "resolution_summary": "Reboot everything",
        "suggested_fix": "Restart pod",
        "confidence": 0.4,
    }

    with patch.object(mem, "_index_resolution_in_qdrant", new_callable=AsyncMock) as mock_index:
        record = await mem.store_resolution(
            session=mock_session,
            incident_id=inc_id,
            resolution_data=res_data,
            approved=False,
            reviewer_feedback="Not acceptable"
        )
        assert record.status == "REJECTED"
        assert record.human_approval is False
        mock_session.commit.assert_called_once()
        mock_index.assert_not_called()
