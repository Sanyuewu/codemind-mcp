FROM python:3.12-slim

# git is required by the find_references and git_blame tools
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reproducible dependency management
RUN pip install uv --no-cache-dir

WORKDIR /app

# Install dependencies first (cached layer unless pyproject.toml/uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application source
COPY src/ ./src/
COPY main.py ./

# /repo  — mount your target code repository here (read-only recommended)
# /data  — persistent storage for the vector index and SQLite metadata
VOLUME ["/repo", "/data"]

ENV CODEMIND_REPO_PATH=/repo
ENV CODEMIND_DATA_DIR=/data
ENV CODEMIND_LOG_FORMAT=json

# MCP communicates over stdio; no port is exposed
CMD ["uv", "run", "python", "main.py"]
