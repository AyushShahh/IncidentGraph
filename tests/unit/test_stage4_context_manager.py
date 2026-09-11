"""Unit tests for Stage 4 Context Manager."""
import pytest
from backend.agent.context_manager import ContextManager


@pytest.fixture
def ctx_mgr():
    return ContextManager(token_budget=4000)


def test_estimate_tokens(ctx_mgr):
    assert ctx_mgr.estimate_tokens("") == 0
    assert ctx_mgr.estimate_tokens("abcd") == 1
    assert ctx_mgr.estimate_tokens("a" * 400) == 100


def test_summarize_tool_output_error(ctx_mgr):
    out = ctx_mgr.summarize_tool_output("read_file", {"error": "File not found"})
    assert out["relevance"] == "error"
    assert "File not found" in out["finding_summary"]


def test_summarize_tool_output_read_file(ctx_mgr):
    # Short lines
    short_content = "line1\nline2\nline3"
    res = ctx_mgr.summarize_tool_output("read_file", {
        "file_path": "services/order.py",
        "content": short_content,
        "start_line": 1,
        "end_line": 3
    })
    assert res["relevance"] == "source_code"
    assert res["file_path"] == "services/order.py"
    assert "line1\nline2\nline3" == res["code_snippet"]
    assert "3 lines" in res["finding_summary"]

    # Long lines (>14 lines)
    long_content = "\n".join([f"line_{i}" for i in range(25)])
    res_long = ctx_mgr.summarize_tool_output("read_file", {
        "file_path": "services/order.py",
        "content": long_content,
        "start_line": 1,
        "end_line": 25
    })
    assert "lines omitted" in res_long["code_snippet"]
    assert res_long["line_range"] == "1-26" or "1-" in res_long["line_range"]


def test_summarize_tool_output_search_code(ctx_mgr):
    # Empty
    empty = ctx_mgr.summarize_tool_output("search_code", [])
    assert empty["relevance"] == "empty"

    # With results
    results = [{
        "file_path": "services/inventory.py",
        "content": "def allocate():\n    pass",
        "start_line": 10,
        "end_line": 20,
        "similarity_score": 0.92,
        "symbols": ["allocate"]
    }]
    res = ctx_mgr.summarize_tool_output("search_code", results)
    assert res["relevance"] == "code_search"
    assert res["file_path"] == "services/inventory.py"
    assert "allocate" in res["finding_summary"]


def test_summarize_tool_output_find_symbol(ctx_mgr):
    empty = ctx_mgr.summarize_tool_output("find_symbol", [])
    assert empty["relevance"] == "empty"

    symbols = [{
        "name": "reserve_stock",
        "symbol_type": "function",
        "file_path": "services/inventory.py",
        "start_line": 42,
        "end_line": 55,
        "signature": "def reserve_stock(sku: str, qty: int) -> bool:"
    }]
    res = ctx_mgr.summarize_tool_output("find_symbol", symbols)
    assert res["relevance"] == "symbol_definition"
    assert "reserve_stock" in res["finding_summary"]
    assert res["code_snippet"] == "def reserve_stock(sku: str, qty: int) -> bool:"


def test_summarize_tool_output_topology(ctx_mgr):
    topo_dict = {"summary": "Direct callers: ['orders', 'checkout']"}
    res = ctx_mgr.summarize_tool_output("find_callers", topo_dict)
    assert res["relevance"] == "topology"
    assert "Direct callers" in res["finding_summary"]

    topo_list = ["orders", "checkout"]
    res_list = ctx_mgr.summarize_tool_output("lookup_dependencies", topo_list)
    assert res_list["relevance"] == "topology"
    assert "orders" in res_list["finding_summary"]


def test_summarize_tool_output_routes_config_dirs(ctx_mgr):
    routes = [{"method": "POST", "path": "/checkout"}]
    res = ctx_mgr.summarize_tool_output("get_service_routes", routes)
    assert res["relevance"] == "routes"
    assert "POST /checkout" in res["finding_summary"]

    cfg = {"service": "payments", "config_name": "Dockerfile", "content": "FROM python:3.11\nRUN pip install ..."}
    res_cfg = ctx_mgr.summarize_tool_output("read_config", cfg)
    assert res_cfg["relevance"] == "configuration"
    assert "Dockerfile" in res_cfg["finding_summary"]

    dir_listing = {"service": "payments", "path": ".", "entries": [{"name": "main.py", "is_directory": False}]}
    res_dir = ctx_mgr.summarize_tool_output("list_directory", dir_listing)
    assert res_dir["relevance"] == "directory_listing"
    assert "main.py" in res_dir["finding_summary"]


def test_is_duplicate_call(ctx_mgr):
    visited_files = {"services/inventory.py"}
    visited_symbols = {"reserve_stock"}

    # Duplicate file
    assert ctx_mgr.is_duplicate_call("read_file", {"file_path": "services/inventory.py"}, visited_files, visited_symbols)
    assert not ctx_mgr.is_duplicate_call("read_file", {"file_path": "services/orders.py"}, visited_files, visited_symbols)

    # Duplicate symbol
    assert ctx_mgr.is_duplicate_call("find_symbol", {"symbol_name": "reserve_stock"}, visited_files, visited_symbols)
    assert not ctx_mgr.is_duplicate_call("find_symbol", {"symbol_name": "process_payment"}, visited_files, visited_symbols)

    # Line ranges: same file with different line range is NOT duplicate
    visited_ranges = {"services/inventory.py:1-30"}
    assert ctx_mgr.is_duplicate_call(
        "read_lines",
        {"file_path": "services/inventory.py", "start_line": 1, "end_line": 30},
        visited_files,
        visited_symbols,
        visited_ranges=visited_ranges,
    )
    assert not ctx_mgr.is_duplicate_call(
        "read_lines",
        {"file_path": "services/inventory.py", "start_line": 50, "end_line": 80},
        visited_files,
        visited_symbols,
        visited_ranges=visited_ranges,
    )

    # Search queries
    visited_queries = {"exchange_rates"}
    assert ctx_mgr.is_duplicate_call("search_code", {"query": "EXCHANGE_RATES"}, visited_files, visited_symbols, visited_queries)
    assert not ctx_mgr.is_duplicate_call("search_code", {"query": "convert_currency"}, visited_files, visited_symbols, visited_queries)

    # Unrestricted tools when no query set passed
    assert not ctx_mgr.is_duplicate_call("search_code", {"query": "test"}, visited_files, visited_symbols)


def test_build_working_context_prompt(ctx_mgr):
    state = {
        "primary_service": "inventory",
        "title": "Deadlock in allocation",
        "error_message": "DatabaseLockTimeout: deadlock detected",
        "error_trace": "File a.py, line 1\nFile b.py, line 2\nFile c.py, line 3\nException: deadlock",
        "evidence": [
            {
                "source_tool": "find_symbol",
                "finding_summary": "reserve_stock defined in inventory.py",
                "code_snippet": "def reserve_stock(): pass"
            }
        ],
        "hypothesis": {
            "root_cause_statement": "Lock ordering violation in inventory allocation",
            "failure_mechanism": "Thread 1 locks SKU A then B, Thread 2 locks SKU B then A",
            "confidence": 0.88
        },
        "visited_files": ["services/inventory.py"]
    }

    prompt = ctx_mgr.build_working_context_prompt(state)
    assert "### INCIDENT" in prompt
    assert "inventory" in prompt
    assert "Deadlock in allocation" in prompt
    assert "### ERROR TRACE (TAIL)" in prompt
    assert "### VERIFIED EVIDENCE ITEMS" in prompt
    assert "reserve_stock" in prompt
    assert "### CURRENT HYPOTHESIS" in prompt
    assert "Lock ordering violation" in prompt
    assert "Already inspected files: services/inventory.py" in prompt

    # Verify that total estimated tokens is within bounds (< 1000 tokens)
    tokens = ctx_mgr.estimate_tokens(prompt)
    assert tokens < 500
