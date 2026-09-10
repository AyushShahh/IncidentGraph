"""Mock LLM provider for deterministic unit and integration testing."""
import json
from typing import Any, Callable, Dict, List, Optional
from backend.agent.providers.base import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    """Deterministic mock provider that returns configured responses or invokes a callback."""

    def __init__(
        self,
        model_name: str = "mock-model",
        default_response: Optional[str] = None,
    ) -> None:
        super().__init__(model_name=model_name)
        self.default_response = default_response
        self.response_queue: List[str] = []
        self.recorded_calls: List[List[Dict[str, str]]] = []
        self.custom_handler: Optional[Callable[[List[Dict[str, str]]], str]] = None

    def queue_response(self, response: Any) -> None:
        """Queue a string or dict (serialized to JSON) for the next call."""
        if isinstance(response, (dict, list)):
            self.response_queue.append(json.dumps(response))
        else:
            self.response_queue.append(str(response))

    def set_handler(self, handler: Callable[[List[Dict[str, str]]], str]) -> None:
        """Register a custom callback function to dynamically inspect messages and return output."""
        self.custom_handler = handler

    def clear(self) -> None:
        """Reset state."""
        self.response_queue.clear()
        self.recorded_calls.clear()
        self.custom_handler = None

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """Record messages and return the next queued response or default."""
        self.recorded_calls.append(list(messages))

        if self.custom_handler:
            return self.custom_handler(messages)

        if self.response_queue:
            return self.response_queue.pop(0)

        if self.default_response is not None:
            return self.default_response

        # Intelligent schema-aware mock defaults based on prompt contents
        all_text = " ".join([m.get("content", "") for m in messages])
        if "InvestigationPlan" in all_text or "target_tool" in all_text:
            return json.dumps({
                "objective": "Inspect error site in service entrypoint",
                "target_tool": {
                    "tool_name": "read_lines",
                    "tool_args": {"service": "inventory", "file_path": "main.py", "start_line": 1, "end_line": 35},
                    "rationale": "Verify implementation around failure site",
                },
                "expected_finding": "Locate failure trigger",
                "stop_recommended": False,
            })
        elif "Hypothesis" in all_text or "root_cause_statement" in all_text:
            return json.dumps({
                "root_cause_statement": "DatabaseLockTimeout caused by resource contention",
                "failure_mechanism": "Concurrent transactions compete for lock without consistent ordering",
                "affected_component": "inventory.service",
                "confidence": 0.90,
                "evidence_ids": ["ev-1"],
                "missing_evidence": [],
            })
        elif "ReviewResult" in all_text or "approved_for_fix" in all_text:
            return json.dumps({
                "is_valid": True,
                "critique": "Hypothesis is well supported by stack trace and code inspection.",
                "approved_for_fix": True,
                "confidence_score": 0.90,
                "suggested_actions": ["Add explicit ORDER BY or transaction isolation"],
            })
        elif "FinalReport" in all_text or "remediation_plan" in all_text:
            return json.dumps({
                "incident_id": "test-inc",
                "primary_service": "inventory",
                "root_cause": "Deadlock in inventory reservation lock ordering",
                "evidence": [],
                "confidence": 0.90,
                "suggested_fix": "Sort SKU IDs before acquiring row locks",
                "references": ["services/inventory/main.py"],
                "reasoning_summary": "Confirmed deadlock vulnerability through code audit",
                "resolution_status": "AWAITING_APPROVAL",
            })

        return '{"status": "ok"}'
