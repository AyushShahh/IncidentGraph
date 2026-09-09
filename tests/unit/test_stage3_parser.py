"""Unit tests for Stage 3 AST parser, route/call extractor, and document chunker."""
from backend.repository.parser import CodeParser
from backend.repository.schemas import ChunkType, SymbolType

SAMPLE_PYTHON_CODE = """\"\"\"Sample microservice implementation.\"\"\"
import os
from fastapi import FastAPI, HTTPException

SERVICE_NAME = "sample_service"
MAX_RETRIES = 3
TARGET_URL = os.getenv("TARGET_SERVICE_URL", "http://orders:8002")

app = FastAPI()


class OrderPayload:
    def __init__(self, order_id: str):
        self.order_id = order_id

    def validate(self) -> bool:
        \"\"\"Validate payload structure.\"\"\"
        return bool(self.order_id)


@app.post("/api/submit", summary="Submit order")
async def submit_order(payload: dict):
    \"\"\"Process incoming order submission.\"\"\"
    res = await http_client.post(f"{TARGET_URL}/orders", json=payload)
    return res


def calculate_tax(amount: float) -> float:
    return amount * 0.1
"""

SAMPLE_MARKDOWN = """# Service Documentation

This service handles order management.

## Architecture
The service connects to Postgres and Kafka.

### Endpoints
- POST /orders
"""


def test_parse_python_symbols():
    """Verify AST extraction of functions, classes, methods, constants, and routes."""
    parser = CodeParser(service_name="sample")
    symbols, outbound, chunks = parser.parse_python_file("main.py", SAMPLE_PYTHON_CODE)

    sym_names = {s.name: s for s in symbols}

    # Constants
    assert "SERVICE_NAME" in sym_names
    assert sym_names["SERVICE_NAME"].symbol_type == SymbolType.CONSTANT
    assert "MAX_RETRIES" in sym_names

    # Classes and methods
    assert "OrderPayload" in sym_names
    assert sym_names["OrderPayload"].symbol_type == SymbolType.CLASS

    assert "OrderPayload.validate" in sym_names
    assert sym_names["OrderPayload.validate"].symbol_type == SymbolType.METHOD
    assert "Validate payload structure" in (sym_names["OrderPayload.validate"].docstring or "")

    # Routes
    assert "submit_order" in sym_names
    route_sym = sym_names["submit_order"]
    assert route_sym.symbol_type == SymbolType.ROUTE
    assert route_sym.route_info is not None
    assert route_sym.route_info.method == "POST"
    assert route_sym.route_info.path == "/api/submit"
    assert route_sym.route_info.summary == "Submit order"

    # Ordinary function
    assert "calculate_tax" in sym_names
    assert sym_names["calculate_tax"].symbol_type == SymbolType.FUNCTION


def test_parse_python_outbound_calls():
    """Verify extraction of outbound HTTP calls and target service hints."""
    parser = CodeParser(service_name="sample")
    _, outbound, _ = parser.parse_python_file("main.py", SAMPLE_PYTHON_CODE)

    assert len(outbound) >= 1
    http_call = next((c for c in outbound if c.call_type == "http"), None)
    assert http_call is not None
    assert http_call.caller_service == "sample"
    assert http_call.http_method == "POST"
    # Target hint should resolve to orders
    assert http_call.target_service_hint == "orders"


def test_chunk_markdown():
    """Verify markdown chunking by headers."""
    parser = CodeParser(service_name="sample")
    chunks = parser.parse_markdown_file("README.md", SAMPLE_MARKDOWN)

    assert len(chunks) == 3
    assert chunks[0].chunk_type == ChunkType.DOC
    assert "Service Documentation" in chunks[0].symbol_names
    assert "Architecture" in chunks[1].symbol_names
    assert "Endpoints" in chunks[2].symbol_names
