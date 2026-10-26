# Execution sandbox for Blind-Tester generated tests (Python: pytest, JavaScript/TypeScript: Jest, Java: JUnit 5).
# Build from the worker/ directory:
#   docker build -t sceptic-sandbox:latest -f worker/sandbox/Dockerfile worker
# The container runs with --network none, a read-only code mount, and no capabilities (see worker/sandbox_runner.py).
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jdk-headless nodejs npm curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Python runner
RUN pip install --no-cache-dir pytest==8.3.5

# JavaScript / TypeScript runner: Jest and ts-jest, pinned by the lockfile in worker/tools/js
COPY tools/js/package.json tools/js/package-lock.json /opt/sceptic-js/
RUN cd /opt/sceptic-js && npm ci --no-audit --no-fund \
 && npm cache clean --force
ENV NODE_PATH=/opt/sceptic-js/node_modules

# Java runner: JUnit Platform console launcher, verified by SHA-256 at build time
ARG JUNIT_VERSION=1.11.4
ARG JUNIT_SHA256=b016ef6b1c3454d6d7c2c88ce081dabf289699686af6622d6e4e2e1b54b4a2fc
RUN mkdir -p /opt/junit \
 && curl -sSfL -o /opt/junit/junit-platform-console-standalone.jar \
      "https://repo1.maven.org/maven2/org/junit/platform/junit-platform-console-standalone/${JUNIT_VERSION}/junit-platform-console-standalone-${JUNIT_VERSION}.jar" \
 && echo "${JUNIT_SHA256}  /opt/junit/junit-platform-console-standalone.jar" | sha256sum -c -

WORKDIR /work
USER 65534:65534
