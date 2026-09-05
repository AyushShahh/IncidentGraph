.PHONY: help up down ps logs test test-fast test-real traffic seed

help:
	@echo "Available commands:"
	@echo "  make up          - Start all microservices and infrastructure in Docker"
	@echo "  make down        - Stop all containers"
	@echo "  make ps          - List running container statuses"
	@echo "  make logs        - Tail container logs"
	@echo "  make test        - Run fast integration and unit tests in Docker"
	@echo "  make test-fast   - Run fast integration tests (ASGITransport)"
	@echo "  make test-real   - Run real integration tests (live Docker & Kafka)"
	@echo "  make traffic     - Run realistic traffic generator against Gateway"
	@echo "  make seed        - Verify database connectivity"

up:
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f

test: test-fast

test-fast:
	docker compose run --rm test-runner pytest tests/unit tests/integration/test_service_apis.py tests/integration/test_trace_propagation.py tests/integration/test_failure_simulation.py tests/integration/test_health_logging.py -v

test-real:
	docker compose run --rm test-runner pytest tests/integration/test_docker_real_kafka.py -v

traffic:
	docker compose run --rm test-runner python scripts/generate_traffic.py --gateway-url http://gateway:8001 --rate 5 --duration 10

seed:
	docker compose run --rm test-runner python scripts/seed_db.py
