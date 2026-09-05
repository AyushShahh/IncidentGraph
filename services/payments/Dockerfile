FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app"

COPY services/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY services/payments/ ./services/payments/

EXPOSE 8003

CMD ["uvicorn", "services.payments.main:app", "--host", "0.0.0.0", "--port", "8003"]
