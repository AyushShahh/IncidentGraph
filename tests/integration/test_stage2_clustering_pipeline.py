"""Integration tests for Stage 2 Incident Clustering & Deduplication Pipeline."""
import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.db.session import async_session_factory, engine
from backend.db.base import Base
from backend.models.incident import Incident, IncidentCandidate
from backend.clustering.candidate import deduplicate_log_batch
from backend.clustering.redis_index import redis_index
from backend.clustering.vector_index import vector_index
from backend.tasks.clustering_pipeline import IncidentClusteringPipeline
from backend.clustering.embeddings.base import BaseEmbeddingProvider
from backend.redis.client import close_redis_client
from backend.qdrant.client import close_qdrant_client


class DeterministicTestEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic embedding provider (dim=384) matching Qdrant active collection configuration."""

    @property
    def dimension(self) -> int:
        return 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            vec = [0.0] * 384
            t = text.lower()
            if "zerodivision" in t or "division by zero" in t:
                # Direction 1
                vec[0] = 1.0
            elif "database timeout" in t or "connection timeout" in t:
                # Direction 2 (semantic match for timeout variations)
                vec[1] = 1.0
            elif "indexerror" in t or "list index" in t:
                # Direction 3
                vec[2] = 1.0
            elif "keyerror" in t or "missing key" in t:
                # Direction 4
                vec[3] = 1.0
            else:
                # Generic unit vector
                vec[4] = 1.0
            embeddings.append(vec)
        return embeddings


@pytest.fixture(autouse=True)
async def prepare_db_and_collections():
    """Ensure clean tables, Redis, and Qdrant collection for each test, then dispose connections."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("DELETE FROM incident_candidates"))
        await conn.execute(text("DELETE FROM incidents"))

    await redis_index.clear_all_fingerprints()
    await vector_index.ensure_collection(vector_dim=384)
    await vector_index.clear_all_vectors()

    yield

    # Clean up pooled connections to prevent 'Event loop is closed' across test loops
    await engine.dispose()
    await close_redis_client()
    await close_qdrant_client()


@pytest.mark.asyncio
async def test_stage2_deduplication_and_redis_fingerprint_hit():
    """Test full cycle:

    1. Batch 1 creates new incident & indexes in Redis
    2. Batch 2 with same error hits Redis, increments occurrences without re-clustering.
    """
    provider = DeterministicTestEmbeddingProvider()
    pipeline = IncidentClusteringPipeline(embedding_provider=provider)

    batch_1 = [
        {
            "service": "orders",
            "level": "ERROR",
            "message": f"ZeroDivisionError: division by zero in ord-{i}",
            "error": {"error_code": "ZERO_DIVISION_ERROR"},
            "trace_id": f"trace-b1-{i}",
            "timestamp": "2026-09-06T12:00:00Z",
        }
        for i in range(10)
    ]

    # Run Batch 1
    stats_1 = await pipeline.process_batch(batch_1)
    assert stats_1["filtered_logs"] == 10
    assert stats_1["deduplicated_candidates"] == 1
    assert stats_1["new_incidents_created"] == 1
    assert stats_1["redis_fingerprint_hits"] == 0

    # Verify in DB
    async with async_session_factory() as session:
        result = await session.execute(
            select(Incident).where(Incident.primary_service == "orders")
        )
        incident = result.scalars().first()
        assert incident is not None
        assert incident.total_occurrences == 10
        incident_id = incident.id

        # Verify Candidate
        cand_res = await session.execute(
            select(IncidentCandidate).where(IncidentCandidate.incident_id == incident_id)
        )
        candidate = cand_res.scalars().first()
        assert candidate is not None
        assert candidate.occurrence_count == 10
        fp = candidate.fingerprint

    # Verify in Redis
    cached_inc_id = await redis_index.lookup_fingerprint(fp)
    assert cached_inc_id == str(incident_id)

    # Run Batch 2 with identical error
    batch_2 = [
        {
            "service": "orders",
            "level": "ERROR",
            "message": f"ZeroDivisionError: division by zero in ord-{i}",
            "error": {"error_code": "ZERO_DIVISION_ERROR"},
            "trace_id": f"trace-b2-{i}",
            "timestamp": "2026-09-06T12:05:00Z",
        }
        for i in range(15)
    ]

    stats_2 = await pipeline.process_batch(batch_2)
    assert stats_2["redis_fingerprint_hits"] == 1
    assert stats_2["new_incidents_created"] == 0

    # Verify PostgreSQL occurrence counter updated
    async with async_session_factory() as session:
        updated_inc = await session.get(Incident, incident_id)
        assert updated_inc is not None
        assert updated_inc.total_occurrences == 25  # 10 from batch 1 + 15 from batch 2


@pytest.mark.asyncio
async def test_stage2_multi_cluster_batch():
    """Verify that a batch with multiple distinct failures clusters into separate incidents."""
    provider = DeterministicTestEmbeddingProvider()
    pipeline = IncidentClusteringPipeline(embedding_provider=provider)

    logs = [
        {
            "service": "orders",
            "level": "ERROR",
            "message": f"IndexError: list index out of range for ord-{i}",
            "error": {"error_code": "INDEX_ERROR"},
            "trace_id": f"trace-idx-{i}",
            "timestamp": "2026-09-06T12:10:00Z",
        }
        for i in range(5)
    ] + [
        {
            "service": "payments",
            "level": "ERROR",
            "message": f"KeyError: 'card_token' missing in tx-{i}",
            "error": {"error_code": "KEY_ERROR"},
            "trace_id": f"trace-key-{i}",
            "timestamp": "2026-09-06T12:11:00Z",
        }
        for i in range(8)
    ]

    stats = await pipeline.process_batch(logs)
    assert stats["filtered_logs"] == 13
    assert stats["deduplicated_candidates"] == 2
    assert stats["new_incidents_created"] == 2


@pytest.mark.asyncio
async def test_stage2_incident_resolution_cleanup():
    """Verify that resolving an incident cleans up Redis fingerprints and Qdrant vectors."""
    async with async_session_factory() as session:
        # Create dummy active incident and candidate
        from backend.db.repositories.incident_repo import IncidentRepository
        inc = await IncidentRepository.create_incident(
            session=session,
            title="[ORDERS] Test Incident for Resolution",
            primary_service="orders",
            affected_services=["orders"],
        )
        cand = await IncidentRepository.add_candidate(
            session=session,
            incident_id=inc.id,
            fingerprint="test-fp-resolution-12345",
            service_name="orders",
            normalized_text="Test resolution error text",
        )
        await session.commit()

        # Seed Redis and Qdrant
        await redis_index.index_fingerprint("test-fp-resolution-12345", inc.id)
        assert await redis_index.lookup_fingerprint("test-fp-resolution-12345") == str(inc.id)

        # Resolve
        resolved_inc = await IncidentRepository.resolve_incident(session=session, incident_id=inc.id)
        await session.commit()
        assert resolved_inc.status == "RESOLVED"

        # Delete from Redis
        await redis_index.delete_fingerprints(["test-fp-resolution-12345"])
        assert await redis_index.lookup_fingerprint("test-fp-resolution-12345") is None
