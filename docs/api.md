# API Documentation

The platform exposes RESTful endpoints at `/api/v1` with interactive OpenAPI docs at `/api/v1/docs`.

## Endpoints

### 1. Health Checks
- `GET /api/v1/health/`: Liveness probe.
- `GET /api/v1/health/ready`: Readiness probe verifying Postgres, Kafka, Redis, and Qdrant.

### 2. Incident Management
- `GET /api/v1/incidents/`: List all incidents with pagination and status filters.
- `POST /api/v1/incidents/`: Ingest or trigger a manual incident.
- `GET /api/v1/incidents/{incident_id}`: Retrieve detailed incident info, logs, and remediation.
- `POST /api/v1/incidents/{incident_id}/approve`: Submit human reviewer approval or rejection for proposed fix.

### 3. Analysis & Reasoning
- `POST /api/v1/analysis/trigger`: Trigger LangGraph analysis workflow for an incident.
- `GET /api/v1/analysis/{incident_id}/status`: Inspect in-flight reasoning execution status.
