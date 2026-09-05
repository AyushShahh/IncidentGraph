FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app"

COPY services/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY services/orders/ ./services/orders/

EXPOSE 8002

CMD ["uvicorn", "services.orders.main:app", "--host", "0.0.0.0", "--port", "8002"]
