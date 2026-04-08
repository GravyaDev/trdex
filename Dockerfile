FROM python:3.12-slim

WORKDIR /app

# curl is needed by the docker-compose healthcheck (curl -sf .../v1/health).
# Without it the healthcheck always reports unhealthy and the depends_on
# wait in the lifespan stalls forever.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching.
# README.md is required because pyproject.toml declares ``readme = "README.md"``;
# without it ``uv sync`` errors out with "Readme file does not exist".
COPY pyproject.toml uv.lock* README.md ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy source code
COPY src/ src/

# Expose FastAPI port
EXPOSE 8000

CMD ["uv", "run", "python", "-m", "trdex.main"]
