# ── ZeroWall Demo Target App — Dockerfile ──────────────────────────────────
FROM python:3.11-slim AS base

LABEL maintainer="ZeroWall Demo"
LABEL description="Intentionally Vulnerable FastAPI Target — ZeroWall Hackathon Demo"

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Default environment
ENV PORT=8000
ENV APP_VERSION=v1.0.0-ORIGINAL
ENV DEPLOY_HASH=aabbcc001122

EXPOSE 8000

# Health check — used by docker-compose and ZeroWall deploy controller
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "main.py"]
