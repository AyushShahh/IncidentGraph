"""Incident candidate data structures and in-batch log deduplication logic."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set

from backend.clustering.normalizer import normalizer
from backend.clustering.fingerprint import fingerprint_log


@dataclass
class IncidentCandidateData:
    """Represents a deduplicated error cluster candidate item within a processing batch."""

    fingerprint: str
    normalized_text: str
    representative_log: Dict[str, Any]
    service_name: str
    error_code: Optional[str]
    event_type: Optional[str]
    deployment_version: Optional[str]
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    sample_trace_ids: List[str] = field(default_factory=list)
    all_trace_ids: Set[str] = field(default_factory=set)
    embedding: Optional[List[float]] = None
    embedding_id: Optional[str] = None

    @property
    def embedding_text(self) -> str:
        """Normalized representation formatted for dense embedding generation.

        Strictly represents pure error semantics without service names or dynamic variables,
        ensuring service names do not distort semantic clustering in vector space.
        """
        err = self.error_code or ""
        text = self.normalized_text or ""
        if err and err not in text:
            return f"{err}: {text}"
        return text or "Unknown error event"

    def has_trace_overlap(self, other: "IncidentCandidateData") -> bool:
        """Check if this candidate shares any distributed trace IDs with another candidate."""
        if not self.all_trace_ids or not other.all_trace_ids:
            return False
        return bool(self.all_trace_ids & other.all_trace_ids)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize candidate data to dictionary."""
        return {
            "fingerprint": self.fingerprint,
            "normalized_text": self.normalized_text,
            "service_name": self.service_name,
            "error_code": self.error_code,
            "event_type": self.event_type,
            "deployment_version": self.deployment_version,
            "occurrence_count": self.occurrence_count,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "sample_trace_ids": self.sample_trace_ids,
            "representative_log": self.representative_log,
            "embedding_id": self.embedding_id,
        }


def _parse_log_timestamp(log: dict) -> datetime:
    """Safely parse timestamp from log dictionary with UTC fallback."""
    raw_ts = log.get("timestamp") or log.get("time")
    if raw_ts:
        try:
            if isinstance(raw_ts, str):
                return datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            elif isinstance(raw_ts, (int, float)):
                return datetime.fromtimestamp(raw_ts, timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def deduplicate_log_batch(raw_logs: List[Dict[str, Any]]) -> List[IncidentCandidateData]:
    """Collapse identical normalized error logs within a single batch into candidates.

    Aggregates occurrence counts, preserves earliest/latest timestamps,
    maintains complete trace ID sets for in-batch causal graph correlation,
    and collects up to 10 sample trace IDs for serialization without losing count integrity.
    """
    candidates_by_fp: Dict[str, IncidentCandidateData] = {}

    for log in raw_logs:
        if not isinstance(log, dict):
            continue

        # 1. Normalize text
        normalized_text = normalizer.extract_and_normalize(log)

        # 2. Compute stable fingerprint
        fp = fingerprint_log(log, normalized_text)

        # Extract metadata
        service_name = log.get("service") or log.get("service_name") or "unknown"
        error_info = log.get("error") or {}
        error_code = log.get("error_code")
        if not error_code:
            if isinstance(error_info, dict):
                error_code = error_info.get("error_code") or error_info.get("type")
            elif isinstance(error_info, str):
                error_code = error_info

        event_type = log.get("event_type")
        deployment_version = log.get("deployment_version")
        ts = _parse_log_timestamp(log)

        # Trace ID
        trace_id = log.get("trace_id") or log.get("traceId")
        if not trace_id:
            ctx = log.get("context") or {}
            if isinstance(ctx, dict):
                trace_id = ctx.get("trace_id")

        tid_str = str(trace_id) if trace_id else None

        if fp in candidates_by_fp:
            candidate = candidates_by_fp[fp]
            candidate.occurrence_count += 1
            if ts < candidate.first_seen:
                candidate.first_seen = ts
            if ts > candidate.last_seen:
                candidate.last_seen = ts
            if tid_str:
                candidate.all_trace_ids.add(tid_str)
                if tid_str not in candidate.sample_trace_ids and len(candidate.sample_trace_ids) < 10:
                    candidate.sample_trace_ids.append(tid_str)
        else:
            sample_traces = [tid_str] if tid_str else []
            all_traces = {tid_str} if tid_str else set()
            candidates_by_fp[fp] = IncidentCandidateData(
                fingerprint=fp,
                normalized_text=normalized_text,
                representative_log=log,
                service_name=service_name,
                error_code=error_code,
                event_type=event_type,
                deployment_version=deployment_version,
                occurrence_count=1,
                first_seen=ts,
                last_seen=ts,
                sample_trace_ids=sample_traces,
                all_trace_ids=all_traces,
            )

    return list(candidates_by_fp.values())
