# Shared image for all four pipeline microservices.
# docker-compose runs this ONE image four times, each with a different uvicorn
# command and a single actor key -> per-container key isolation.
FROM python:3.12-slim

WORKDIR /app

# Python deps (Polygon-only; the circular backend is never imported in containers
# because BLOCKCHAIN=polygon, and factory.py imports backends lazily).
COPY requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt

# Application code (self-contained image).
COPY src/ ./src/
COPY requirements.lock.txt ./

# data/, artifacts/ and certificates/ are provided at RUNTIME via a shared
# volume so the pipeline stages can pass files between containers.

# uvicorn must bind 0.0.0.0 (set in each service command) so containers are
# reachable from each other and from the host.
EXPOSE 8000 8001 8002 8003

# Default command (overridden per-service in docker-compose.yml).
CMD ["uvicorn", "api.orchestrator_api:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]