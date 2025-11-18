# syntax=docker/dockerfile:1.6

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install Python dependencies inside a dedicated virtual environment.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# Copy application source code.
COPY . .

# Prepare runtime directories and non-root user for Cloud Run.
RUN groupadd --system appuser \
    && useradd --system --gid appuser --create-home appuser \
    && mkdir -p /app/documents /app/.secrets \
    && chown -R appuser:appuser /app /opt/venv

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "uvicorn src.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
