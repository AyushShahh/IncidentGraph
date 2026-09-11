# IncidentGraph: REST & WebSocket API Documentation

The IncidentGraph platform exposes a versioned RESTful API under `/api/v1` alongside a real-time WebSocket event stream. Interactive OpenAPI / Swagger documentation is available at `http://localhost:8000/docs`.

---

## 1. Platform Health & Readiness

### Liveness Probe
```http
GET /health
GET /api/v1/health
```
- **Response `200 OK`**:
```json
{
  "status": "healthy",
  "service": "AI Incident Intelligence Platform",
  "version": "0.1.0",
  "environment": "development"
}
```

### Readiness Probe
Verifies network connectivity and authentication against PostgreSQL, Redis, Kafka, and Qdrant.
```http
GET /health/ready
GET /api/v1/health/ready
```
- **Response `200 OK`**:
```json
{
  "status": "ready",
  "service": "AI Incident Intelligence Platform",
  "checks": {
    "postgres": "ready",
    "redis": "ready",
    "kafka": "ready",
    "qdrant": "ready"
  }
}
```

---

## 2. Incident Management

### List Incidents
Retrieves clustered causal incidents with pagination and filtering.
```http
GET /api/v1/incidents?page=1&page_size=20&status=ACTIVE&service=payments
```
- **Query Parameters**:
  - `page` (int, default: 1)
  - `page_size` (int, default: 20)
  - `status` (string: `ACTIVE`, `INVESTIGATING`, `AWAITING_APPROVAL`, `RESOLVED`, `REJECTED`, `SUPPRESSED`)
  - `service` (string, optional service filter)
- **Response `200 OK`**:
```json
{
  "total": 4,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": "b96b9448-92bf-4dff-a7c2-be17388b85dd",
      "title": "KeyError in payments",
      "status": "AWAITING_APPROVAL",
      "severity": "HIGH",
      "primary_service": "payments",
      "affected_services": ["payments", "orders"],
      "total_occurrences": 12,
      "first_seen": "2026-09-11T07:15:00Z",
      "last_seen": "2026-09-11T07:18:22Z",
      "candidates_count": 1,
      "resolution": {
        "root_cause": "Unsupported currency code 'GBP' in EXCHANGE_RATES dictionary.",
        "suggested_fix": "Add fallback default or explicit currency validation.",
        "status": "AWAITING_APPROVAL",
        "confidence": 0.95
      }
    }
  ]
}
```

### Get Incident by ID
```http
GET /api/v1/incidents/{incident_id}
```
- **Response `200 OK`**: Returns full incident details, associated error candidates, and current resolution if available.
- **Response `404 Not Found`**: When incident ID does not exist.

---

## 3. Autonomous Investigations Agent

### Trigger Agent Investigation
Initiates the LangGraph autonomous multi-node investigation workflow.
```http
POST /api/v1/investigations/run
POST /api/v1/agent/run
```
- **Request Body**:
```json
{
  "incident_id": "b96b9448-92bf-4dff-a7c2-be17388b85dd",
  "primary_service": "payments",
  "max_iterations": 5,
  "confidence_threshold": 0.85,
  "auto_approve": false
}
```
- **Response `200 OK`**:
```json
{
  "incident_id": "b96b9448-92bf-4dff-a7c2-be17388b85dd",
  "primary_service": "payments",
  "status": "AWAITING_APPROVAL",
  "confidence": 0.95,
  "cached_solution_found": false,
  "iterations": 2,
  "tokens_used": 1420,
  "final_report": {
    "root_cause": "The application raises a KeyError when accessing EXCHANGE_RATES with unsupported currency 'GBP'.",
    "suggested_fix": "Use .get(payload.currency, DEFAULT_RATE) or raise HTTPException(400).",
    "inspected_files": ["services/payments/main.py"],
    "confidence": 0.95
  }
}
```

### Get Investigation State
Retrieves the real-time execution checkpoint, iteration count, gathered evidence, and hypothesis for an in-flight or completed investigation.
```http
GET /api/v1/investigations/{incident_id}
GET /api/v1/agent/{incident_id}
```
- **Response `200 OK`**:
```json
{
  "incident_id": "b96b9448-92bf-4dff-a7c2-be17388b85dd",
  "primary_service": "payments",
  "status": "AWAITING_APPROVAL",
  "approval_status": "AWAITING_APPROVAL",
  "confidence": 0.95,
  "iteration_count": 2,
  "tokens_used": 1420,
  "evidence": [
    {
      "evidence_id": "ev-1",
      "source_tool": "trace_parser",
      "file_path": "services/payments/main.py",
      "line_range": "88-118",
      "finding_summary": "Stack trace error site around line 88-118"
    }
  ],
  "hypothesis": {
    "root_cause_statement": "KeyError on missing currency",
    "confidence": 0.95
  },
  "final_report": { ... }
}
```

### Submit Human Review (Approve or Reject)
Submits operator approval or rejection for the investigated resolution patch.
```http
POST /api/v1/investigations/{incident_id}/approve
POST /api/v1/agent/{incident_id}/approve
```
- **Request Body**:
```json
{
  "approved": true,
  "reviewer_feedback": "Validated on payments service, approved for automated fix."
}
```
- **Response `200 OK`**:
```json
{
  "message": "Investigation resolution APPROVED successfully.",
  "incident_id": "b96b9448-92bf-4dff-a7c2-be17388b85dd",
  "status": "APPROVED",
  "human_approval": true,
  "reviewer_feedback": "Validated on payments service, approved for automated fix.",
  "resolution": { ... }
}
```
*Note: Approved resolutions are immediately embedded and indexed into Qdrant `incident_resolutions` for instant future incident reuse (0-token cache hit).*

---

## 4. Repository Intelligence & Topology

### Discover Services
```http
GET /api/v1/repositories/discover
```
- **Response `200 OK`**: Returns all discovered microservices in `services/`.

### Trigger Indexing
```http
POST /api/v1/repositories/index?force=false
```
- Performs incremental SHA256 diff index across AST symbols and Qdrant vector code chunks.

### Full Dependency Graph
```http
GET /api/v1/repositories/dependency-graph
```
- **Response `200 OK`**: Returns Cytoscape.js compatible graph JSON containing service nodes, database/broker storage nodes, and directed call edges.

### Blast Radius Calculation
Calculates the architectural blast radius and impacted downstream routes if a target service fails.
```http
GET /api/v1/repositories/blast-radius/{service}
```
- **Response `200 OK`**:
```json
{
  "target_service": "payments",
  "direct_dependents": ["gateway"],
  "transitive_dependents": ["gateway"],
  "criticality_score": 0.75,
  "impacted_routes": [
    { "service": "gateway", "method": "POST", "path": "/api/checkout" }
  ],
  "summary": "Failure impacts gateway and checkout routes."
}
```

### Semantic Code Search
```http
GET /api/v1/repositories/search?q=EXCHANGE_RATES&service=payments
```
- Returns top semantic and lexical code chunk matches with line ranges and symbol annotations.

---

## 5. Platform Statistics

### Fleet & Incident Stats
```http
GET /api/v1/stats/platform
```
- **Response `200 OK`**:
```json
{
  "active_incidents": 2,
  "resolved_incidents": 8,
  "total_candidates": 45,
  "autonomous_resolutions": 7,
  "resolution_success_rate": 87.5,
  "services_count": 5
}
```

---

## 6. Real-Time WebSocket Streaming

- **Endpoint**: `ws://localhost:8000/ws` (or `ws://localhost:3000/ws` via Nginx reverse proxy)
- **Protocol**: JSON payload with `type`, `incident_id`, and `data` fields.

### Event Types Broadcasted:
| Event Type | Trigger | Payload Details |
| :--- | :--- | :--- |
| `incident:created` | Novel incident formed by clustering pipeline | Incident ID, title, primary service, severity |
| `incident:updated` | State change (`INVESTIGATING`, `RESOLVED`, `REJECTED`) | Incident ID, status, severity |
| `agent:start` | Investigation agent invoked | Incident ID, service |
| `agent:step` | Agent finishes iteration step | Iteration count, tool executed, confidence |
| `agent:hypothesis` | New root cause hypothesis formed | Root cause statement, confidence |
| `agent:fix_ready` | Remediation proposal finalized (`AWAITING_APPROVAL`) | Proposed code fix, root cause |
| `agent:approved` | Operator approves resolution | Resolution status, reviewer note |
| `agent:rejected` | Operator rejects proposed fix | Resolution status, reviewer note |
