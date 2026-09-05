"""Structured logging configuration for backend platform."""
import logging
import sys
from pythonjsonlogger import jsonlogger
from backend.core.config import settings


def setup_logging() -> None:
    """Configures structured JSON logging format for stdout."""
    log_handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(message)s"
    )
    log_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    root_logger.handlers = [log_handler]

    # Silence overly verbose external libraries
    logging.getLogger("aiokafka").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    # TODO: Add OpenTelemetry log handler integration for distributed tracing


def get_logger(name: str) -> logging.Logger:
    """Return configured logger instance."""
    return logging.getLogger(name)
