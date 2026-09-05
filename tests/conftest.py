"""Shared Pytest fixtures for Stage 1 microservices and fast integration tests."""
import asyncio
from unittest.mock import AsyncMock, patch
from typing import AsyncGenerator
import pytest
import pytest_asyncio
import httpx

from services.gateway.main import app as gateway_app, target_service_clients as gw_clients
from services.orders.main import app as orders_app, target_service_clients as ord_clients, ORDERS
from services.payments.main import app as payments_app, target_service_clients as pay_clients, TRANSACTIONS
from services.inventory.main import app as inventory_app, STOCK_STORE, DEFAULT_STOCK
from services.notifications.main import app as notifications_app, NOTIFICATION_HISTORY
from shared.kafka.producer import get_shared_kafka_producer
from shared.schemas.log_event import LogEventSchema


@pytest.fixture
def kafka_spy():
    """Test spy capturing dispatched Kafka log events without keeping mock code in production."""
    dispatched_events: list[LogEventSchema] = []
    producer = get_shared_kafka_producer()

    async def mock_send_log(log_event, topic=None, key=None):
        if isinstance(log_event, LogEventSchema):
            dispatched_events.append(log_event)
        return True

    original_is_started = producer.is_started
    producer.is_started = True
    with patch.object(producer, "send_log", side_effect=mock_send_log):
        try:
            yield dispatched_events
        finally:
            producer.is_started = original_is_started


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset in-memory datastores before and after each test to ensure test isolation."""
    STOCK_STORE.clear()
    STOCK_STORE.update(DEFAULT_STOCK)
    ORDERS.clear()
    TRANSACTIONS.clear()
    NOTIFICATION_HISTORY.clear()

    yield

    STOCK_STORE.clear()
    STOCK_STORE.update(DEFAULT_STOCK)
    ORDERS.clear()
    TRANSACTIONS.clear()
    NOTIFICATION_HISTORY.clear()


@pytest_asyncio.fixture
async def service_network():
    """Wire in-memory ASGI clients between microservices for fast end-to-end integration."""
    inv_transport = httpx.ASGITransport(app=inventory_app)
    notif_transport = httpx.ASGITransport(app=notifications_app)
    orders_transport = httpx.ASGITransport(app=orders_app)
    payments_transport = httpx.ASGITransport(app=payments_app)
    gateway_transport = httpx.ASGITransport(app=gateway_app)

    async with (
        httpx.AsyncClient(transport=inv_transport, base_url="http://inventory:8004") as inv_client,
        httpx.AsyncClient(transport=notif_transport, base_url="http://notifications:8005") as notif_client,
        httpx.AsyncClient(transport=orders_transport, base_url="http://orders:8002") as ord_client,
        httpx.AsyncClient(transport=payments_transport, base_url="http://payments:8003") as pay_client,
        httpx.AsyncClient(transport=gateway_transport, base_url="http://gateway:8001") as gw_client,
    ):
        # Wire client references into caller services
        ord_clients["inventory"] = inv_client
        ord_clients["notifications"] = notif_client
        pay_clients["notifications"] = notif_client
        gw_clients["orders"] = ord_client
        gw_clients["payments"] = pay_client

        yield {
            "gateway": gw_client,
            "orders": ord_client,
            "payments": pay_client,
            "inventory": inv_client,
            "notifications": notif_client,
        }

        # Cleanup references
        ord_clients.clear()
        pay_clients.clear()
        gw_clients.clear()
