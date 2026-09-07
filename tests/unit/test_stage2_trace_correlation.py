"""Unit tests for distributed trace co-occurrence graph correlation and root candidate resolution."""
from datetime import datetime, timezone
import pytest

from backend.clustering.candidate import IncidentCandidateData
from backend.tasks.clustering_pipeline import IncidentClusteringPipeline


def _make_candidate(
    fp: str,
    service: str,
    error_code: str,
    trace_ids: list[str],
    event_type: str = "error",
    exception: str = None,
    downstream: str = None,
) -> IncidentCandidateData:
    now = datetime.now(timezone.utc)
    rep_log = {
        "service": service,
        "error_code": error_code,
        "event_type": event_type,
    }
    if exception:
        rep_log["exception"] = exception
    if downstream:
        rep_log["downstream_service"] = downstream

    return IncidentCandidateData(
        fingerprint=fp,
        normalized_text=f"{error_code} details in {service}",
        representative_log=rep_log,
        service_name=service,
        error_code=error_code,
        event_type=event_type,
        deployment_version="v1.0.0",
        occurrence_count=1,
        first_seen=now,
        last_seen=now,
        sample_trace_ids=trace_ids,
        all_trace_ids=set(trace_ids),
    )


def test_trace_graph_groups_multi_service_cascade():
    """Verify that 3 candidates from 3 different services sharing a trace ID form 1 connected component."""
    pipeline = IncidentClusteringPipeline()

    c_gw = _make_candidate("fp-gw", "gateway", "OUT_OF_STOCK", ["trace-req-1"], downstream="orders")
    c_ord = _make_candidate("fp-ord", "orders", "OUT_OF_STOCK", ["trace-req-1"], downstream="inventory")
    c_inv = _make_candidate("fp-inv", "inventory", "OUT_OF_STOCK", ["trace-req-1"], event_type="stock_reservation_failed")

    # Another independent candidate with a different trace ID
    c_other = _make_candidate("fp-other", "payments", "TIMEOUT", ["trace-req-99"])

    candidates = [c_gw, c_ord, c_inv, c_other]
    groups = pipeline._extract_trace_connected_components(candidates)

    assert len(groups) == 2

    # Group 1 should contain the 3 cascade candidates
    cascade_group = next(g for g in groups if len(g) == 3)
    services = {c.service_name for c in cascade_group}
    assert services == {"gateway", "orders", "inventory"}

    # Group 2 should contain only payments
    other_group = next(g for g in groups if len(g) == 1)
    assert other_group[0].service_name == "payments"


def test_resolve_root_candidate_identifies_origin():
    """Verify that root candidate is resolved to the origin service with unhandled exception or innermost depth."""
    pipeline = IncidentClusteringPipeline()

    c_gw = _make_candidate("fp-gw", "gateway", "IndexError", ["t1"], downstream="orders")
    c_ord = _make_candidate("fp-ord", "orders", "IndexError", ["t1"], downstream="inventory")
    c_inv = _make_candidate(
        "fp-inv",
        "inventory",
        "IndexError",
        ["t1"],
        event_type="unhandled_exception",
        exception="IndexError: list index out of range",
    )

    root = pipeline._resolve_root_candidate([c_gw, c_ord, c_inv])
    assert root.service_name == "inventory"
    assert root.error_code == "IndexError"
