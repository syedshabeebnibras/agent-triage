# Backend container for the Agent Triage API.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Copy demo data so the deployed API can serve sample runs
COPY data ./data

EXPOSE 8000
# Use the CLI's serve command (uvicorn under the hood)
CMD ["uvicorn", "agent_triage.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
