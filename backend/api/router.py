"""Aggregate router mounting API v1 routes."""
from fastapi import APIRouter
from backend.api.v1 import health
from backend.api.v1 import incidents
from backend.api.v1 import repository
from backend.api.v1 import agent
from backend.api.v1 import ws
from backend.api.v1 import stats

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(incidents.router, prefix="/incidents", tags=["Incidents"])
api_router.include_router(repository.router, prefix="/repositories", tags=["Repository Intelligence"])
api_router.include_router(repository.context_router, prefix="/context", tags=["Context Engine"])
api_router.include_router(agent.router, prefix="/investigations", tags=["Investigation Agent"])
api_router.include_router(ws.router, prefix="/ws", tags=["Real-time Streaming"])
api_router.include_router(stats.router, prefix="/stats", tags=["Platform Stats"])

