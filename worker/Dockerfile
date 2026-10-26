FROM python:3.11-slim

WORKDIR /app

# System tools for the verifiers: git (Gatekeeper workflow check), curl (downloads), JDK and Maven (javac and
# Maven classpath for the Java Fact-Checker), Node.js and npm (tsc and the JS/TS tooling).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    ca-certificates \
    default-jdk-headless \
    maven \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Pinned open-source scanners, each verified by SHA-256 at build time.
ARG GITLEAKS_VERSION=8.30.1
ARG GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
ARG OSV_SCANNER_VERSION=2.7.0
ARG OSV_SCANNER_SHA256=160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b
RUN curl -sSfL -o /tmp/gitleaks.tgz \
      "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
 && echo "${GITLEAKS_SHA256}  /tmp/gitleaks.tgz" | sha256sum -c - \
 && tar -xzf /tmp/gitleaks.tgz -C /usr/local/bin gitleaks \
 && rm -f /tmp/gitleaks.tgz \
 && curl -sSfL -o /usr/local/bin/osv-scanner \
      "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_amd64" \
 && echo "${OSV_SCANNER_SHA256}  /usr/local/bin/osv-scanner" | sha256sum -c - \
 && chmod +x /usr/local/bin/osv-scanner /usr/local/bin/gitleaks

# Create unprivileged non-root user for container security
RUN useradd -m -u 1000 sceptic && chown -R sceptic:sceptic /app

# Pinned JavaScript/TypeScript tooling (tsc for the verifier), installed from the lockfile
COPY worker/tools/js/package.json worker/tools/js/package-lock.json /app/worker/tools/js/
RUN cd /app/worker/tools/js && npm ci --no-audit --no-fund && npm cache clean --force

# Copy and install Python dependencies
COPY worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy worker logic and backend modules (models & database required by worker tasks)
COPY worker /app/worker
COPY backend /app/backend

# Configure module paths and buffering
ENV PYTHONPATH=/app/worker:/app/backend:/app
ENV PYTHONUNBUFFERED=1
ENV OSV_SCANNER_PATH=/usr/local/bin/osv-scanner

USER sceptic

WORKDIR /app/worker

CMD ["celery", "-A", "celery_app.celery_app", "worker", "--loglevel=info"]
