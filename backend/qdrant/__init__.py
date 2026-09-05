"""Qdrant vector store connection and indexing utilities."""
from backend.qdrant.client import get_qdrant_client, init_collections

__all__ = ["get_qdrant_client", "init_collections"]
