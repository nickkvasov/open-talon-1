FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy source and config
COPY pyproject.toml .
COPY app/ app/
COPY web/ web/
COPY tui/ tui/

# Install Python deps
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e "."

# Default port
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
