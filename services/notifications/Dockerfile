FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app"

COPY services/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY services/notifications/ ./services/notifications/

EXPOSE 8005

CMD ["uvicorn", "services.notifications.main:app", "--host", "0.0.0.0", "--port", "8005"]
