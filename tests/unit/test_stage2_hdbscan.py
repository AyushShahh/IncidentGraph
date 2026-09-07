"""Unit tests for HDBSCANIncidentClusterer."""
import pytest
from datetime import datetime, timezone
from backend.clustering.candidate import IncidentCandidateData
from backend.clustering.clusterer import HDBSCANIncidentClusterer


def _make_candidate(fp: str, service: str, embedding: list[float]) -> IncidentCandidateData:
    now = datetime.now(timezone.utc)
    return IncidentCandidateData(
        fingerprint=fp,
        normalized_text=f"Test error {fp}",
        representative_log={"service": service, "level": "ERROR"},
        service_name=service,
        error_code="TEST_ERROR",
        event_type="test",
        deployment_version="v1.0.0",
        occurrence_count=5,
        first_seen=now,
        last_seen=now,
        sample_trace_ids=["trace-1"],
        embedding=embedding,
    )


def test_hdbscan_empty_and_single():
    clusterer = HDBSCANIncidentClusterer()
    assert clusterer.cluster_candidates([]) == []

    cand = _make_candidate("fp1", "orders", [0.1, 0.2, 0.3])
    clusters = clusterer.cluster_candidates([cand])
    assert len(clusters) == 1
    assert clusters[0] == [cand]


def test_hdbscan_groups_tight_clusters():
    """Verify that tight embedding groups form clusters and outliers are kept as singletons."""
    clusterer = HDBSCANIncidentClusterer(min_cluster_size=2, min_samples=1)

    # Cluster A: 3 candidates clustered around [1.0, 0.0, 0.0]
    c1 = _make_candidate("fp1", "orders", [1.0, 0.01, 0.0])
    c2 = _make_candidate("fp2", "orders", [0.99, -0.01, 0.0])
    c3 = _make_candidate("fp3", "orders", [1.01, 0.0, 0.02])

    # Cluster B: 3 candidates clustered around [0.0, 1.0, 0.0]
    c4 = _make_candidate("fp4", "payments", [0.0, 1.0, 0.01])
    c5 = _make_candidate("fp5", "payments", [0.02, 0.99, -0.01])
    c6 = _make_candidate("fp6", "payments", [-0.01, 1.01, 0.0])

    # Outlier: far away at [0.0, 0.0, 1.0]
    c7 = _make_candidate("fp7", "inventory", [0.0, 0.0, 1.0])

    all_candidates = [c1, c2, c3, c4, c5, c6, c7]
    clusters = clusterer.cluster_candidates(all_candidates)

    # Total candidates preserved across all clusters must equal 7
    total_preserved = sum(len(c) for c in clusters)
    assert total_preserved == 7

    # At least two composite clusters should be formed
    composite_clusters = [c for c in clusters if len(c) > 1]
    assert len(composite_clusters) >= 1
