FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed for Tree-Sitter parsing & security scanners
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged non-root user for container security
RUN useradd -m -u 1000 sceptic && chown -R sceptic:sceptic /app

# Copy and install Python dependencies
COPY worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy worker logic and backend modules (models & database required by worker tasks)
COPY worker /app/worker
COPY backend /app/backend

# Configure module paths and buffering
ENV PYTHONPATH=/app/worker:/app/backend:/app
ENV PYTHONUNBUFFERED=1

USER sceptic

WORKDIR /app/worker

CMD ["celery", "-A", "celery_app.celery_app", "worker", "--loglevel=info"]
