# ===========================
# Stock Agent Dockerfile
# ===========================

# Stage 1: Build frontend
FROM docker.m.daocloud.io/library/node:22-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy package files first for better caching
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy frontend source and build (skip TypeScript checking for faster build)
COPY frontend/ .
RUN npx vite build

# Stage 2: Python backend + static files
FROM docker.m.daocloud.io/library/python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies (using Chinese mirror for faster downloads in China)
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv (using Chinese PyPI mirror for faster downloads in China)
RUN pip install uv -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

WORKDIR /app

# Copy Python project files
COPY pyproject.toml uv.lock ./
COPY backend/ backend/
COPY config.yaml ./
COPY extensions_config.json ./

# Install Python dependencies (using Chinese PyPI mirror)
RUN uv pip install --system -e ".[akshare,yfinance]" -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Create data and log directories
RUN mkdir -p /app/data /app/log

# Copy .env.example as default config
COPY .env.example .env

# Expose port
EXPOSE 6666

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:6666/health || exit 1

# Run the application
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "6666"]
