# Sceptic Deployment & DevOps Foundation (Phase 9)

This document describes the multi-container deployment architecture of Sceptic, designed to support containerized execution and provide a realistic target for post-deployment verification agents.

---

## 1. Multi-Container Architecture Overview

Sceptic runs as a 6-container topology communicating across an isolated internal bridge network (`sceptic-network` in development, `sceptic-prod-network` in production):

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
       INDEPENDENT TARGET FOR DEVOPS VERIFICATION:
       ─────────────────────────────────────────────────────
                   ┌─────────────────────────┐
                   │     Target Service      │
                   │   (FastAPI / Port 8080) │
                   │  /health, /version, demo│
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
