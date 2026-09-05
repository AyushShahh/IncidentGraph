FROM python:3.12-slim

WORKDIR /app

# Target CPU or GPU via Docker build args
# Default to cu124 for GPU, change to 'cpu' for CPU-only build
ARG TARGET_DEVICE=cu132
ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch conditionally based on architecture and TARGET_DEVICE
# 1. ARM64 (e.g. Apple Silicon) doesn't support CUDA wheels -> install CPU
# 2. x86_64 uses TARGET_DEVICE (cu126, cu130, cu132, or cpu)
# Add no cache dir to pip install
RUN if [ "$TARGETARCH" = "arm64" ] || [ "$TARGET_DEVICE" = "cpu" ]; then \
    echo "Installing CPU/ARM PyTorch..." && \
    pip install torch --index-url https://download.pytorch.org/whl/cpu; \
    else \
    echo "Installing PyTorch with CUDA (${TARGET_DEVICE})..." && \
    pip install torch --index-url https://download.pytorch.org/whl/${TARGET_DEVICE}; \
    fi

# Install python dependencies
# Add no cache dir to pip install
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy configuration and code
COPY pyproject.toml .
COPY backend/ ./backend/
COPY shared/ ./shared/
COPY scripts/ ./scripts/
COPY services/ ./services/
COPY tests/ ./tests/

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
