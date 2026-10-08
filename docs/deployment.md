# Sceptic Deployment & DevOps Foundation (Phase 9)

This document describes the multi-container deployment architecture of Sceptic, designed to support containerized execution and provide a realistic target for post-deployment verification agents.

---

## 1. Multi-Container Architecture Overview

Sceptic runs as an 8-container topology communicating across an isolated internal bridge network (`sceptic-network` in development, `sceptic-prod-network` in production):

```text
                           ┌─────────────────────────┐
                           │     React Frontend      │
                           │   (Port 5173 / Vite)    │
                           └────────────┬────────────┘
                                        │ HTTP
                                        ▼
                           ┌─────────────────────────┐
                           │     FastAPI Backend     │
                           │       (Port 8000)       │
                           └──────┬────────────┬─────┘
                                  │            │
                         Tasks /  │            │ Async DB
                         Events   ▼            ▼
                   ┌─────────────┐       ┌──────────────┐
                   │    Redis    │       │  PostgreSQL  │
                   │ (Port 6379) │       │ (Port 5432)  │
                   └──────┬──────┘       └──────────────┘
                          │                      ▲
                          ▼                      │
                   ┌─────────────┐               │
                   │   Celery    │───────────────┘
                   │   Worker    │ (Result persistence & audits)
                   └─────────────┘

       ─────────────────────────────────────────────────────
       INDEPENDENT TARGET & OBSERVABILITY FOUNDATION:
       ─────────────────────────────────────────────────────
                   ┌─────────────────────────┐
                   │     Target Service      │
                   │  (FastAPI / Port 8080)  │
                   │  /health, /version,     │
                   │  /metrics, /api/fail    │
                   └────────────┬────────────┘
                                │ Scrape (every 5s)
                                ▼
                   ┌─────────────────────────┐
                   │       Prometheus        │
                   │       (Port 9090)       │
                   └────────────┬────────────┘
                                │ Query API
                                ▼
                   ┌─────────────────────────┐
                   │         Grafana         │
                   │       (Port 3000)       │
                   │ Sceptic Dashboard       │
                   └─────────────────────────┘
```

### Services Summary

| Service | Technology | Port (Host:Container) | Purpose |
| :--- | :--- | :--- | :--- |
| `backend` | FastAPI / Uvicorn | `8000:8000` | Core API, project management, auth, audit endpoints |
| `frontend` | React / Vite / TypeScript | `5173:5173` | Interactive dashboard & findings explorer |
| `worker` | Celery / Python | (internal only) | Asynchronous verification agent pipeline execution |
| `redis` | Redis 7 Alpine | `6380:6379` (dev) | Celery task queue broker and result backend |
| `postgres` | PostgreSQL 15 Alpine | `5432:5432` | Local relational database for audits and users |
| `target-service` | FastAPI / Python | `8080:8080` | Independent deployment target application |
| `prometheus` | Prometheus v2.51.0 | `9090:9090` | Timeseries metric scraper and storage engine |
| `grafana` | Grafana 10.4.0 | `3000:3000` | Automated dashboards and telemetry visualization |

---

## 2. Target Service Specification

The target service (`target_service/`) is an independent, deployable application used as a target for post-deployment verification (such as health probing, drift detection, and rollback).

### Endpoints

- `GET /health`:
  - Returns `{"status": "healthy"}`
  - Used by container health checks and pipeline watchdogs.
- `GET /version`:
  - Exposes runtime build and deployment metadata:
    ```json
    {
      "version": "1.0.0",
      "commit_sha": "dev-initial",
      "build_timestamp": "2026-10-07T00:00:00Z",
      "environment": "development"
    }
    ```
- `GET /api/demo`:
  - Returns functional payload:
    ```json
    {
      "service": "target-service",
      "message": "Target application is running successfully.",
      "items": [
        {"id": 1, "name": "item-alpha"},
        {"id": 2, "name": "item-beta"}
      ]
    }
    ```

---

## 3. How to Start the Stack

### Prerequisites
- Docker Engine 24+ & Docker Compose v2+
- (Optional for host testing) Python 3.12+ with virtual environment

### Development Environment (Local)

1. Copy environment variables:
   ```bash
   cp .env.example .env
   ```
2. Start all 6 services:
   ```bash
   docker compose up --build
   ```
   Or in detached mode:
   ```bash
   docker compose up -d --build
   ```
3. Check container statuses:
   ```bash
   docker compose ps
   ```

### Production-Like Environment

To run the production profile with JSON-file log rotation (`max-size: 10m`, `max-file: 3`), append-only Redis persistence, and `always` restart policies:

```bash
docker compose -f infra/docker-compose.prod.yml up -d --build
```

---

## 4. Verification & Health Probing

Once the services are running, verify each endpoint:

- **Target Service Health:**
  ```bash
  curl http://localhost:8080/health
  # {"status":"healthy"}
  ```
- **Target Service Version Metadata:**
  ```bash
  curl http://localhost:8080/version
  # {"version":"1.0.0","commit_sha":"...","build_timestamp":"...","environment":"development"}
  ```
- **Backend Health:**
  ```bash
  curl http://localhost:8000/health
  # Returns status, database, and redis status
  ```
- **Frontend UI:**
  Navigate to `http://localhost:5173` in a web browser.

---

## 5. Database Configuration & Fallbacks

Sceptic supports two database modes via `.env`:

1. **Local Docker PostgreSQL:**
   By default, `docker-compose.yml` launches a local `postgres:15-alpine` container with a named volume `sceptic_postgres_data`.
2. **External PostgreSQL / Supabase:**
   Set `DATABASE_URL` in `.env` to your external connection string:
   ```bash
   DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
   ```
   The backend and worker will prioritize the environment variable without data loss or schema resets.

---

## 6. Running Tests

To run the automated test suite across all services (including the target service):

```bash
# Run target service tests
pytest target_service/test_target_service.py -v

# Run full project test suite
pytest target_service/ worker/ cli/ backend/ -v
```

---

## 7. Deployment State & Observability Models (Phase 10)

Phase 10 introduces the persistent database schema required for post-deployment observability, drift tracking, and recovery.

### Relational Hierarchy

```text
User
 └── Project
       ├── PullRequests
       ├── AuditRuns
       ├── FeatureAnalyses
       └── Deployments
             ├── TelemetrySnapshots
             ├── DriftEvents
             └── RollbackRecords
```

### Models

- **`Deployment`**: Represents an individual application deployment record attached to a `Project`.
  - Captures `commit_sha`, `image_name`, `image_tag`, `image_digest`, `environment`, `version`, `status` (`PENDING`, `DEPLOYING`, `ACTIVE`, `FAILED`, `ROLLED_BACK`), and timestamps.
  - Supports self-referential linking via `previous_deployment_id` with safe `ON DELETE SET NULL` constraints to preserve deployment history.
- **`TelemetrySnapshot`**: Persists structured metric snapshots associated with a deployment.
  - Stores `health_status`, `request_count`, `error_count`, `error_rate`, `latency_avg`, and `latency_p95`.
  - Serves as the storage foundation for post-deployment health and performance observation.
- **`DriftEvent`**: Records configuration or image discrepancies between expected and observed state.
  - Tracks `drift_type` (`COMMIT`, `IMAGE`, `IMAGE_DIGEST`, `CONFIGURATION`, `ENVIRONMENT`), `expected_value`, `actual_value`, `severity`, and detection timestamps.
- **`RollbackRecord`**: Records recovery actions and target restore points for a deployment.
  - Links the originating `deployment_id` with `target_deployment_id`, storing `reason`, `trigger_source`, `status`, and safety check results.

### API Endpoints

- `POST /projects/{project_id}/deployments`: Create new deployment under an owned project.
- `GET /projects/{project_id}/deployments`: List all deployments for a project.
- `GET /deployments/{deployment_id}`: Retrieve deployment metadata (enforces `Deployment -> Project -> User` ownership).
- `GET /deployments/{deployment_id}/telemetry` & `POST`: List or record telemetry snapshots.
- `GET /deployments/{deployment_id}/drift` & `POST`: List or record drift events.
- `GET /deployments/{deployment_id}/rollbacks` & `POST`: List or record rollback operations.

---

## 8. CI/CD Pipeline & Automated Deployment (Phase 11)

Phase 11 implements the GitHub Actions automation for continuous integration, Docker image packaging, GitHub Container Registry (GHCR) publishing, and health-verified deployment.

### Pipeline Flow

```text
git push / PR
      │
      ▼
.github/workflows/ci.yml
  ├── Python Test Suite (Backend, Worker, CLI, Target Service)
  ├── Frontend Build (React, Vite, Tailwind)
  └── Docker Build & Compose Syntax Validation
      │
      ▼ (Push to main)
.github/workflows/deploy.yml
  ├── Docker Buildx & GHCR Publish
  │     ├── ghcr.io/<owner>/sceptic-backend:<commit-sha>
  │     ├── ghcr.io/<owner>/sceptic-worker:<commit-sha>
  │     ├── ghcr.io/<owner>/sceptic-frontend:<commit-sha>
  │     └── ghcr.io/<owner>/sceptic-target-service:<commit-sha>
  ├── Launch Multi-Container Stack (Docker Compose)
  │     └── Injects COMMIT_SHA, APPLICATION_VERSION, ENVIRONMENT
  └── Post-Deployment Verification (scripts/deploy.py)
        ├── Health Probe: GET /health (HTTP 200, status="healthy")
        ├── Version Check: GET /version (commit_sha match)
        ├── Database State Update:
        │     status: DEPLOYING ──► ACTIVE (Success)
        │     status: DEPLOYING ──► FAILED (Health/Commit Failure)
        └── Safe Termination (No automatic rollback)
```

### GitHub Container Registry (GHCR) Configuration

- **Registry**: `ghcr.io`
- **Authentication**: Uses built-in `secrets.GITHUB_TOKEN`.
- **Permissions Required**:
  ```yaml
  permissions:
    contents: read
    packages: write
  ```
- **Image Tagging**: Every build publishes immutable commit-SHA tags (`:<commit-sha>`) alongside a moving `:latest` convenience tag. The authoritative deployment identifier is strictly the immutable Git commit SHA.

### Deployment Gate & Verification Runner

The deployment runner [`scripts/deploy.py`](../scripts/deploy.py) handles deployment gating and verification:
```bash
python scripts/deploy.py \
  --project-id "00000000-0000-0000-0000-000000000001" \
  --commit-sha "abc123456789" \
  --image-name "ghcr.io/org/sceptic-target-service" \
  --image-tag "abc123456789" \
  --environment "production" \
  --version "1.0.0" \
  --target-url "http://localhost:8080" \
  --backend-url "http://localhost:8000" \
  --timeout 30.0
```

- **Trust Gate Policy**:
  - `APPROVE` ($\ge 85$ points): Deployment permitted.
  - `REQUEST_CHANGES` ($65-84$ points): Deployment halted (`BLOCKED`).
  - `BLOCK` ($< 65$ points): Deployment halted (`BLOCKED`).
- **Failure Behavior**: If readiness probes time out or the running commit does not match the expected commit SHA, the deployment record in PostgreSQL is set to `FAILED`. In compliance with Phase 11 boundaries, no automatic rollback is executed.

---

## 5. Phase 12: Observability Foundation (Prometheus + Grafana)

Phase 12 introduces the foundational timeseries telemetry layer for the Sceptic ecosystem. This foundation provides real runtime metrics to support the future Pipeline Watchdog Agent without premature automation or alerting.

### 5.1 Architecture

```text
[Incoming Traffic] ──► [Target Service :8080]
                             │
                             ├─► /metrics (Prometheus scrapable format)
                             │     - http_requests_total (method, endpoint, status_code)
                             │     - http_request_duration_seconds (method, endpoint, buckets)
                             │     - http_requests_in_progress (method, endpoint)
                             │     - target_service_app_info (version, commit, build, env)
                             │
                             ▼ (Scrape every 5s)
                       [Prometheus :9090]
                             │
                             ▼ (Internal proxy: http://prometheus:9090)
                       [Grafana :3000]
                             │
                             ▼
              [Sceptic Observability Dashboard]
```

### 5.2 Metrics Exported by Target Service

All metrics are exposed at `GET /metrics` in standard Prometheus text format:

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `http_requests_total` | Counter | `method`, `endpoint`, `status_code` | Total HTTP requests processed, partitioned by status code. |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint` | Request execution latency with 11 buckets (`0.005s` to `10.0s`). |
| `http_requests_in_progress` | Gauge | `method`, `endpoint` | Current count of active concurrent requests being processed. |
| `target_service_app_info` | Gauge | `version`, `commit_sha`, `build_timestamp`, `environment` | Constant value `1` carrying deployment identity metadata. |

### 5.3 Metric Safety & Redaction
The metrics implementation strictly enforces security boundaries:
- **Zero Secrets**: No tokens, passwords, API keys, database connection strings, or bearer headers are exposed.
- **Controlled Label Cardinality**: Endpoint paths are normalized (`/health`, `/version`, `/api/demo`, `/metrics`, `/api/fail`) to prevent memory leaks or cardinality explosion.

### 5.4 Failure Simulation Endpoint
For observability verification and future drift/watchdog testing, the target service exposes:
- `GET /api/fail?code=500` (supports `500`, `502`, `503`, `504`): Returns simulated HTTP errors and automatically increments the 5xx status code metrics in `http_requests_total`.

### 5.5 Prometheus Configuration
Defined in [`infra/prometheus/prometheus.yml`](../infra/prometheus/prometheus.yml):
- Scrapes the `target-service` container at `target-service:8080/metrics` every 5 seconds.
- Scrapes self health at `localhost:9090`.

### 5.6 Grafana Provisioning & Dashboard
- **Datasource**: Automatically provisioned from [`infra/grafana/provisioning/datasources/prometheus.yml`](../infra/grafana/provisioning/datasources/prometheus.yml) targeting `http://prometheus:9090`.
- **Dashboards Provider**: Automatically provisioned from [`infra/grafana/provisioning/dashboards/dashboards.yml`](../infra/grafana/provisioning/dashboards/dashboards.yml).
- **Dashboard Definition**: [`infra/grafana/dashboards/definitions/sceptic_observability.json`](../infra/grafana/dashboards/definitions/sceptic_observability.json)
  - **Panels**:
    1. **Target Health (Up Status)**: Stat panel showing target reachability.
    2. **Total Requests**: Stat panel tracking total request count.
    3. **Active In-Progress Requests**: Stat panel tracking concurrent requests.
    4. **Error Rate %**: Percentage of requests returning 5xx status codes.
    5. **Release Metadata**: Displays active Version, Commit SHA, and Environment.
    6. **Request Rate (Throughput)**: Time series graph of requests per second.
    7. **Response Latency (p95)**: Time series graph tracking 95th percentile response times.
    8. **HTTP Status Code Distribution**: Bar chart displaying breakdown of 2xx, 4xx, and 5xx responses.
- **Access**: Open `http://localhost:3000` (Anonymous Viewer enabled for instant access).

---

## 6. Phase 13: Pipeline Watchdog + Deployment Gatekeeper

Phase 13 establishes post-deployment verification by separating runtime behavior monitoring from deployment artifact integrity verification.

```text
                    DEPLOYED SERVICE
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
         Prometheus               /health /version
              │                         │
              └────────────┬────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
        WATCHDOG AGENT             GATEKEEPER
              │                         │
        Runtime Health             Deployment
        Verification               Integrity
              │                         │
              └────────────┬────────────┘
                           │
                           ▼
                  Structured Findings
                           │
                           ▼
                      PostgreSQL
            (TelemetrySnapshots & DriftEvents)
                           │
                           ▼
                 FUTURE ROLLBACK PHASE
```

### 6.1 Pipeline Watchdog
- **Responsibility**: Runtime behavior & performance verification.
- **Inputs**: Deployment ID, target `/health`, Prometheus metrics (`http_requests_total`, `http_request_duration_seconds`).
- **Verifications**:
  1. **Service Health**: Validates `/health` returns HTTP 200 and `status == "healthy"`. Produces `HEALTH_FAILURE` if down.
  2. **Error Rate**: Queries Prometheus for 5xx errors vs total requests. Enforces `WATCHDOG_MIN_REQUESTS` sample protection before triggering `HIGH_ERROR_RATE` to prevent false positives on small sample sizes.
  3. **Latency**: Queries p95 latency via Prometheus histogram quantiles. Produces `HIGH_LATENCY` if p95 exceeds threshold. Returns `UNRESOLVED` if histogram buckets are empty (never invents fake latency).
  4. **Prometheus Availability**: Produces `METRIC_UNAVAILABLE` and `UNRESOLVED` status if Prometheus is unreachable. Never silently passes on telemetry outages.
  5. **Deployment Correlation**: Produces `DEPLOYMENT_CORRELATED_ANOMALY` when degradation is detected following a deployment timestamp.
  6. **Persistence**: Saves real observations to `telemetry_snapshots` table.

### 6.2 Deployment Gatekeeper
- **Responsibility**: Deterministic deployment identity and configuration drift verification.
- **Inputs**: Deployment record vs target `/version` and `/health`.
- **Verifications**:
  1. **Commit SHA**: Compares expected deployment commit against running commit. Produces `COMMIT_MISMATCH`.
  2. **Application Version**: Compares expected version against `/version`. Produces `VERSION_MISMATCH`.
  3. **Environment**: Compares expected environment against running environment. Produces `ENVIRONMENT_MISMATCH`.
  4. **Image Identity**: Compares image digest if available; returns `UNRESOLVED` if runtime digest is unavailable (never fakes PASS).
  5. **Deployment State Alignment**: Flags `DEPLOYMENT_STATE_MISMATCH` if database status is `ACTIVE` but runtime service is unreachable or unaligned.
  6. **Idempotent Drift Persistence**: Saves detected drift into `drift_events` table only if an identical unresolved drift event is not already active.

### 6.3 Absolute No-Rollback Boundary
Neither Pipeline Watchdog nor Gatekeeper may stop, restart, replace, rollback, or alter any container, code, or deployment. They are strictly read-only verification agents that record structured observations into PostgreSQL.

### 6.4 API Endpoints
- `POST /deployments/{id}/watchdog/check`: Runs Watchdog verification and saves telemetry snapshot.
- `POST /deployments/{id}/gatekeeper/check`: Runs Gatekeeper integrity verification and saves drift events.
- `GET /deployments/{id}/telemetry`: Retrieves historical telemetry snapshots.
- `GET /deployments/{id}/drift-events`: Retrieves recorded drift events.

---

## 7. Rollback Agent — Deployment Recovery Engine (Phase 15)

The Sceptic Rollback Agent is responsible for safe, idempotent, and auditable deployment recovery when runtime degradation or integrity drift is detected.

### 7.1 Absolute Safety Principles
Rollback operations modify running infrastructure and must never execute blindly. The Rollback Agent enforces mandatory pre-flight safety checks:
1. **Decision Justification**: Validates that deployment is not already in `ROLLED_BACK` state and a meaningful operational reason is provided.
2. **Previous Known-Good Discovery**:
   - Locates target deployment via explicit user selection, recorded `previous_deployment_id`, or chronological database search for the most recent preceding non-failed deployment.
   - Strictly verifies the target deployment belongs to the same project and is not the current deployment.
3. **Pre-Flight Safety Verifications**:
   - `target_deployment_valid`: Valid target exists in same project.
   - `environment_compatibility`: Target deployment environment must match current deployment environment (prevents staging images in production).
   - `image_availability`: Target image repository and tag must be valid and non-empty.
   - `database_migration_safety`: Verifies database schema compatibility. Flags unsafe downgrades unless overridden via `allow_unsafe_migration=True`.
   - `rollback_lock`: Concurrency guard ensuring no other rollback is currently `IN_PROGRESS` or `PENDING` on this project.
4. **Abort Guard**: If ANY safety check fails:
   - Rollback execution halts immediately.
   - An `ABORTED` record is persisted in `rollback_records` with detailed checklist results.
   - No modifications to running services are permitted.

### 7.2 Post-Rollback Verification
When safety checks pass and the rollback lock is acquired:
1. Execution is dispatched to the recovery executor.
2. The agent waits for service stabilization (`ROLLBACK_HEALTH_TIMEOUT`).
3. Probes `GET /health` to verify HTTP 200 and healthy status.
4. Probes `GET /version` to verify runtime `commit_sha` matches the expected target deployment commit.
5. If verification succeeds:
   - Current deployment status updated to `ROLLED_BACK`.
   - Target deployment status updated to `ACTIVE`.
   - Active drift events on the deployment are resolved (`resolved_at = now()`).
   - `RollbackRecord` updated to `SUCCESS`.
6. If verification fails:
   - Deployment status marked `FAILED`.
   - `RollbackRecord` updated to `FAILED` with detailed diagnostic error message.

### 7.3 API Endpoints
- `POST /deployments/{id}/rollback`: Executes controlled recovery workflow.
- `POST /deployments/{id}/rollback/check`: Evaluates pre-flight safety checks without executing rollback (dry run).
- `GET /deployments/{id}/rollbacks`: Lists all historical rollback records and safety checklists.

### 7.4 CLI Usage
```bash
# Pre-flight safety check (dry run)
sceptic rollback <deployment_id> --dry-run

# Execute safe rollback
sceptic rollback <deployment_id> --reason "Watchdog detected high error rate"

# Rollback to specific target deployment
sceptic rollback <deployment_id> --target <target_deployment_id>
```




