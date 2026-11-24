FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend_requirements.txt
COPY analytics/requirements.txt /app/analytics_requirements.txt
RUN pip install --no-cache-dir -r /app/backend_requirements.txt -r /app/analytics_requirements.txt

COPY db /app/db
COPY analytics /app/analytics
COPY backend/app /app/app
COPY backend/tests /app/tests

RUN mkdir -p /app/generated_reports /app/analytics_outputs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
