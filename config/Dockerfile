# Build context is the repo root (see docker-compose.yml), so COPY paths are
# relative to it. Copy only what the app runs; never `COPY . .` here, the root
# holds .env, local databases and logs.
FROM python:3.11-slim
WORKDIR /app
COPY config/requirements.lock config/requirements.lock
RUN pip install --no-cache-dir -r config/requirements.lock
COPY app/ app/
COPY scripts/ scripts/
COPY migrations/ migrations/
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
