# System Architecture

## Architecture Overview

```text
[ Microservices ]
(gateway, orders, payments, inventory, notifications)
       │
       ▼ (Emit structured logs)
[ Apache Kafka ] (Topic: service-logs)
       │
       ▼
[ HDBSCAN Log Clustering + SentenceTransformers ]
       │
       ▼ (Candidate Incidents)
[ Incident Memory Query (Qdrant) ]
      ├── (Known Incident) ──────────────► [ Reuse Existing Solution ]
      │                                                │
      └── (New Incident)                               ▼
               │                          [ Human Approval Required ]
               ▼                                       │
        [ Context Builder ]                            ▼
        - Microservice Graph (NetworkX)           [ Execute Fix ]
        - Repository Index (Qdrant)                    │
               │                                       ▼
               ▼                          [ Store into Qdrant Memory ]
        [ LangGraph Agent ]
        - Root Cause Reasoning
        - Patch Proposal
```

## Core Modules
- **backend/core**: Environment settings, JSON structured logging.
- **backend/db**: SQLAlchemy async engine, base models, session lifecycles.
- **backend/kafka**: High-throughput async producers and consumers.
- **backend/redis**: Distributed locks, caching, session state.
- **backend/qdrant**: Vector storage for code snippets and incident resolutions.
- **backend/clustering**: HDBSCAN density clustering on semantic embeddings.
- **backend/repository**: AST and code snippet vector indexer.
- **backend/orchestrator**: LangGraph state graph governing incident triage logic.
