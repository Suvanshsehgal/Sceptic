# SCEPTIC — Complete Platform Architecture & Operational Manual

> **Independent AI-Generated Code Verification & Post-Deployment Protection System**

---

## Table of Contents

1. [Executive Summary & Purpose](#1-executive-summary--purpose)
2. [End-to-End System Architecture](#2-end-to-end-system-architecture)
3. [Multi-Container Infrastructure & Topology](#3-multi-container-infrastructure--topology)
4. [Pre-Deployment Verification Agents](#4-pre-deployment-verification-agents)
   - [Fact-Checker Agent](#41-fact-checker-agent)
   - [Blind Tester Agent](#42-blind-tester-agent)
   - [Security Guard Agent](#43-security-guard-agent)
   - [Report Synthesizer & Trust Score Engine](#44-report-synthesizer--trust-score-engine)
   - [Feature Scoper (Pre-Implementation Risk Engine)](#45-feature-scoper)
5. [Post-Deployment Verification & Protection Agents](#5-post-deployment-verification--protection-agents)
   - [Pipeline Watchdog Agent](#51-pipeline-watchdog-agent)
   - [Deployment Gatekeeper Agent](#52-deployment-gatekeeper-agent)
   - [Rollback Agent (Recovery Controller)](#53-rollback-agent-recovery-controller)
6. [Database Schema & State Models](#6-database-schema--state-models)
7. [REST API Complete Reference](#7-rest-api-complete-reference)
8. [CLI Complete Reference](#8-cli-complete-reference)
9. [Observability Stack (Prometheus & Grafana)](#9-observability-stack-prometheus--grafana)
10. [CI/CD & GHCR Deployment Pipeline](#10-cicd--ghcr-deployment-pipeline)
11. [Configuration & Environment Variables](#11-configuration--environment-variables)
12. [Hands-On Runbook & Troubleshooting](#12-hands-on-runbook--troubleshooting)

---

## 1. Executive Summary & Purpose

Modern software development increasingly relies on AI coding assistants (GitHub Copilot, Cursor, Gemini, Claude, ChatGPT) to generate code. While AI accelerates coding speed, it introduces critical failure modes:

- **Hallucinated APIs & Libraries**: Calling methods, parameters, or functions that do not exist or mismatch installed versions.
- **Silent Logic Regressions**: Generating code that appears valid but fails edge cases or contract specifications.
- **Insecure Implementations**: Introducing SQL injection, command execution, hardcoded tokens, or improper cryptographic primitives.
- **Runtime Drift & Silent Deployment Failures**: Containers deploying with configuration mismatch, crashing quietly, or experiencing severe latency.

**Sceptic** provides an independent, multi-layered verification framework operating across two primary lifecycle domains:
1. **Pre-Deployment Verification Pipeline**: Validates code *before* it is merged or deployed using deterministic AST parsing, contract testing, security scanning, and Trust Score gating.
2. **Post-Deployment Protection Engine**: Continuously monitors running applications via timeseries telemetry, verifies configuration drift, and safely executes autonomous rollbacks when deployments degrade.

---

## 2. End-to-End System Architecture

```text
                                CODE CHANGE (PR / Local File)
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │    PRE-DEPLOYMENT VERIFICATION PIPELINE     │
                      └──────────────────────┬───────────────────────┘
                                             │
                      ┌──────────────────────┼───────────────────────┐
                      │                      │                       │
                      ▼                      ▼                       ▼
               Fact-Checker            Blind Tester           Security Guard
              (AST Signatures)       (Contract Tests)      (Semgrep / Bandit)
                      │                      │                       │
                      └──────────────────────┼───────────────────────┘
                                             │
                                             ▼
                                     Report Synthesizer
                                    (Trust Score 0-100)
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       │                                           │
             Trust Score >= 85                           Trust Score < 85
                (APPROVED)                           (REQUEST_CHANGES / BLOCK)
                       │                                           │
                       ▼                                           ▼
               Deployment Permitted                         Deployment Blocked
                       │
                       ▼
          CI/CD GitHub Actions / GHCR
                       │
                       ▼
         Container Deployment to Target
                       │
                       ▼
         ┌──────────────────────────────────────────────────────────┐
         │          POST-DEPLOYMENT PROTECTION ENGINE               │
         └─────────────────────────┬────────────────────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                         │
              ▼                                         ▼
       Pipeline Watchdog                       Deployment Gatekeeper
    (Prometheus Telemetry,                     (Commit SHA, Version,
   Error Rate, p95 Latency)                    Environment, Image Drift)
              │                                         │
              └────────────────────┬────────────────────┘
                                   │
                           Degradation / Drift
                                   │
                                   ▼
                         Rollback Agent Controller
                  (Pre-Flight Safety Checklist & Locks)
                                   │
                           ┌───────┴───────┐
                           │               │
                         PASS            FAIL
                           │               │
                           ▼               ▼
                   Execute Recovery   Stop & Log
                 (Restore Prior Safe  (Persist Abort)
                     Deployment)
```

---

## 3. Multi-Container Infrastructure & Topology

The platform runs as a coordinated 8-container topology defined in [`docker-compose.yml`](file:///D:/Projects/Sceptic/docker-compose.yml):

| Service | Technology | Port (Host:Container) | Role & Description |
| :--- | :--- | :--- | :--- |
| **`backend`** | FastAPI / Python 3.12 | `8000:8000` | Core REST API, project RBAC, authentication, deployment registry. |
| **`frontend`** | React / Vite / TypeScript | `5173:5173` | Web UI dashboard, audit inspector, telemetry visualizer. |
| **`worker`** | Celery / Python | Internal network | Distributed task worker executing async verification pipelines. |
| **`postgres`** | PostgreSQL 15 Alpine | `5432:5432` | Relational database (also supports external Supabase). |
| **`redis`** | Redis 7 Alpine | `6380:6379` | Celery message broker and task result backend. |
| **`target-service`** | FastAPI / Python | `8080:8080` | Independent deployable target application monitored by Sceptic. |
| **`prometheus`** | Prometheus v2.51.0 | `9090:9090` | Timeseries scraper polling target metrics every 5 seconds. |
| **`grafana`** | Grafana 10.4.0 | `3000:3000` | Automated dashboards visualizing latency, errors, and throughput. |

---

## 4. Pre-Deployment Verification Agents

### 4.1 Fact-Checker Agent
- **File**: [`worker/fact_checker.py`](file:///D:/Projects/Sceptic/worker/fact_checker.py)
- **Role**: Deterministic API & Symbol Verification.
- **Methodology**: Uses Python's `ast` (Abstract Syntax Tree) to parse source code without executing it. It resolves external library imports and dynamically inspects module signatures using `importlib` and `inspect.signature()`.
- **Verdict Types**:
  - `VALID`: Function/method exists and argument names/counts match the real signature.
  - `INVALID`: Method does not exist, or required keyword/positional parameters mismatch.
  - `UNRESOLVED`: Code contains dynamic resolution (e.g., `getattr(obj, var)`) that cannot be proven statically.

### 4.2 Blind Tester Agent
- **File**: [`worker/blind_tester.py`](file:///D:/Projects/Sceptic/worker/blind_tester.py)
- **Role**: Specification-Driven Contract Verification.
- **Methodology**: Evaluates function docstrings, type annotations, and formal specifications without looking at the implementation internals (black-box). Generates contract assertion tests and executes them in an isolated sandbox.

### 4.3 Security Guard Agent
- **File**: [`worker/security_guard.py`](file:///D:/Projects/Sceptic/worker/security_guard.py)
- **Role**: Hybrid Static & Contextual Vulnerability Scanner.
- **Methodology**:
  1. **Deterministic AST Rules**: Flags `eval()`, `exec()`, `os.system()`, insecure shell spawns (`shell=True`), and weak hashing (`hashlib.md5`).
  2. **Rule Matchers**: Scans for hardcoded tokens, secret patterns, and OWASP Top 10 vulnerabilities.
  3. **Contextual LLM Analysis**: If `GROQ_API_KEY` is present, assesses whether flagged patterns represent true vulnerabilities or sanitized false positives.

### 4.4 Report Synthesizer & Trust Score Engine
- **File**: [`worker/synthesizer.py`](file:///D:/Projects/Sceptic/worker/synthesizer.py)
- **Role**: Verification Aggregator & Deployment Gating.
- **Trust Score Calculation**:
  $$\text{Trust Score} = 100 - \sum \text{Penalties (Critical: -30, High: -15, Medium: -5, Low: -2)}$$
- **Deployment Verdict**:
  - `APPROVE` ($\ge 85$): Code is verified safe; automated deployment proceeds.
  - `REQUEST_CHANGES` ($65 - 84$): Non-critical flaws detected; requires developer remediation.
  - `BLOCK` ($< 65$): Critical security or API hallucinations detected; deployment blocked.

### 4.5 Feature Scoper
- **File**: [`backend/feature_scoper.py`](file:///D:/Projects/Sceptic/backend/feature_scoper.py)
- **Role**: Pre-Implementation Proposal Analysis.
- **Methodology**: Evaluates user feature proposals against existing codebase architecture. Computes feasibility scores, complexity estimations (Story Points / Hours), security risk classifications, and identifies potential blast radius across project files.

---

## 5. Post-Deployment Verification & Protection Agents

### 5.1 Pipeline Watchdog Agent
- **File**: [`backend/watchdog.py`](file:///D:/Projects/Sceptic/backend/watchdog.py)
- **Question Answered**: *"Is the deployed application behaving correctly at runtime?"*
- **Capabilities**:
  - **Health Probing**: Polls `/health` with strict timeout protection (`WATCHDOG_HEALTH_TIMEOUT`).
  - **Prometheus Telemetry**: Queries `http_requests_total` and `http_request_duration_seconds` to compute real error rate % and p95 latency.
  - **Sample Protection**: Enforces `WATCHDOG_MIN_REQUESTS` (default: 10) so sparse traffic does not trigger false alerts.
  - **Metric Availability Guard**: Reports explicit `UNRESOLVED` if Prometheus is offline (never invents fake PASS).
  - **Persistence**: Records observations directly to the `telemetry_snapshots` database table.

### 5.2 Deployment Gatekeeper Agent
- **File**: [`backend/gatekeeper.py`](file:///D:/Projects/Sceptic/backend/gatekeeper.py)
- **Question Answered**: *"Is the running application actually the artifact and configuration intended to be deployed?"*
- **Capabilities**:
  - **Commit Verification**: Compares expected Git commit SHA against running `/version` payload (`COMMIT_MISMATCH`).
  - **Version & Environment Alignment**: Flags `VERSION_MISMATCH` and `ENVIRONMENT_MISMATCH`.
  - **Image Digest Verification**: Checks container digests; returns `UNRESOLVED` when digests are unavailable.
  - **Idempotent Drift Logging**: Records deviations into `drift_events` only if an identical unresolved drift event is not already open.

### 5.3 Rollback Agent (Recovery Controller)
- **File**: [`backend/rollback_agent.py`](file:///D:/Projects/Sceptic/backend/rollback_agent.py)
- **Question Answered**: *"How do we safely and reliably restore a healthy deployment without human error?"*
- **Absolute Safety Principle**: Rollback **never** executes blindly.
- **The 5 Mandatory Pre-Flight Safety Checks**:
  1. `target_deployment_valid`: Ensures candidate predecessor exists in the same project and is distinct from current deployment.
  2. `environment_compatibility`: Rejects restoring staging builds into production environments.
  3. `image_availability`: Verifies image repository and tag format.
  4. `database_migration_safety`: Blocks schema downgrades unless explicit manual override (`allow_unsafe_migration=True`) is provided.
  5. `rollback_lock`: Concurrency guard ensuring no other rollback is currently `IN_PROGRESS` or `PENDING` on this project.
- **Abort Guard**: If any check fails, execution immediately halts, and an `ABORTED` record is persisted without touching the running service.
- **Post-Rollback Verification**: Probes `/health` (HTTP 200) and `/version` (`commit_sha` exact match). Upon verification, transitions failed deployment to `ROLLED_BACK`, target deployment to `ACTIVE`, resolves active drift events, and persists a `SUCCESS` record in `rollback_records`.

---

## 6. Database Schema & State Models

All relational entities are declared in [`backend/models.py`](file:///D:/Projects/Sceptic/backend/models.py) using SQLAlchemy 2.0 async and migrated with Alembic:

```text
User
 │ 1:N
 ├── AuthAccount (Google OAuth / Local Credentials)
 │
 └── Project (Repository link, branch, configuration)
       │ 1:N
       ├── PullRequest ── 1:N ── AuditRun ── 1:N ── AgentFinding
       │
       ├── FeatureAnalysis (Scoper feasibility, blast radius)
       │
       └── Deployment (commit_sha, image, environment, status)
             │ 1:N
             ├── TelemetrySnapshot (health, error_rate, latency_p95)
             ├── DriftEvent (drift_type, expected, actual, resolved_at)
             └── RollbackRecord (reason, status, safety_check_result)
```

### Deployment Lifecycle Statuses:
- `PENDING`: Created, waiting for deployment runner.
- `DEPLOYING`: In transit / container launching.
- `ACTIVE`: Running in production, healthy.
- `FAILED`: Health probe failed or crashed.
- `ROLLED_BACK`: Replaced by the Rollback Agent during recovery.

### Rollback Record Statuses:
- `PENDING`: Rollback requested.
- `IN_PROGRESS`: Pre-flight checks passed, lock acquired, restoring service.
- `SUCCESS`: Restored, health and commit SHA verified.
- `ABORTED`: Halted by Safety Controller (pre-flight check failed).
- `FAILED`: Execution error or post-rollback verification failed.

---

## 7. REST API Complete Reference

Base URL: `http://localhost:8000`

### Authentication & User
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/auth/register` | Register with Name, Email, Password. |
| `POST` | `/auth/login` | Log in and receive JWT Bearer token. |
| `GET` | `/auth/me` | Fetch authenticated user profile. |
| `GET` | `/auth/google/url` | Get Google OAuth login URL. |
| `GET` | `/auth/google/callback` | OAuth redirect callback handler. |

### Projects
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/projects` | List projects owned by current user. |
| `POST` | `/projects` | Create a new project repository. |
| `GET` | `/projects/{id}` | Get specific project details. |
| `PUT` | `/projects/{id}` | Update project repository settings. |
| `DELETE` | `/projects/{id}` | Delete project and cascaded records. |

### Pre-Deployment Audits & Features
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/projects/{id}/audits` | Trigger audit pipeline on PR or commit. |
| `GET` | `/audits/{audit_id}` | Fetch full audit report, findings, and Trust Score. |
| `POST` | `/projects/{id}/features/evaluate` | Evaluate feature proposal feasibility and risks. |
| `GET` | `/projects/{id}/features` | List historical feature analyses. |

### Deployments, Observability & Rollbacks
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/projects/{id}/deployments` | List deployments for a project. |
| `POST` | `/projects/{id}/deployments` | Register a new deployment. |
| `PATCH`| `/deployments/{id}/status` | Update deployment status (`ACTIVE`, `FAILED`, etc.). |
| `POST` | `/deployments/{id}/watchdog/check` | Execute Pipeline Watchdog runtime health check. |
| `POST` | `/deployments/{id}/gatekeeper/check`| Execute Gatekeeper deployment integrity check. |
| `GET` | `/deployments/{id}/telemetry` | Query recorded telemetry snapshots. |
| `GET` | `/deployments/{id}/drift-events` | Query recorded configuration drift events. |
| `POST` | `/deployments/{id}/rollback/check` | **Dry-Run**: Pre-flight safety check without execution. |
| `POST` | `/deployments/{id}/rollback` | **Execute**: Run full controlled rollback operation. |
| `GET` | `/deployments/{id}/rollbacks` | Retrieve audit history of rollback records. |

---

## 8. CLI Complete Reference

Sceptic provides a rich terminal CLI built with **Typer** and **Rich**:

### Running the Interactive Dashboard
```powershell
.\venv\Scripts\python.exe cli/main.py
```
*(Displays the interactive menu for login, project switching, audits, and health).*

### Direct Command Reference
```powershell
# Diagnostics & Connectivity
sceptic doctor

# Authentication
sceptic login --email <email> --password <pass>
sceptic login --mock-email dev@sceptic.io   # Instant test login
sceptic whoami
sceptic logout

# Project Management
sceptic project list
sceptic project switch <project-id>
sceptic project create <name> <repo-url>

# Pre-Deployment Verification
sceptic audit <file-or-dir>                # In-process audit with all 4 agents
sceptic newfeature                         # Interactive feature scoping wizard
sceptic history                            # View past audit runs

# Post-Deployment & Observability
sceptic status                             # Real-time dashboard status
sceptic watchdog [deployment-id]           # Run Pipeline Watchdog check
sceptic gatekeeper [deployment-id]         # Run Deployment Gatekeeper check

# Rollback Operations
sceptic rollback [deployment-id] --dry-run # Pre-flight safety check
sceptic rollback [deployment-id] --reason "Error rate threshold breached"
sceptic rollback [deployment-id] --target <target-id>
```

---

## 9. Observability Stack (Prometheus & Grafana)

### 1. Prometheus Telemetry (`target_service/main.py`)
The target service instruments real Prometheus metrics exposed on `GET /metrics`:
- `http_requests_total`: Counter partitioned by `method`, `endpoint`, and `status_code`.
- `http_request_duration_seconds`: Histogram measuring latency with 11 buckets ($0.005\text{s}$ to $10.0\text{s}$).
- `http_requests_in_progress`: Real-time in-flight request gauge.
- `target_service_app_info`: Static gauge publishing release metadata (`version`, `commit_sha`, `build_timestamp`, `environment`).

### 2. Grafana Dashboard (`http://localhost:3000`)
Pre-configured with anonymous access to the **Sceptic - Target Service Observability** dashboard featuring 8 real-time panels:
1. Target Service Health (Up/Down)
2. Total HTTP Requests Processed
3. Active Requests In-Progress
4. Error Rate Percentage ($5\text{xx} / \text{Total}$)
5. Deployed Application Identity (Version, SHA, Environment)
6. Request Throughput Rate (req/sec)
7. Response Latency p95 ($\text{seconds}$)
8. HTTP Status Code Distribution

---

## 10. CI/CD & GHCR Deployment Pipeline

Workflows located in `.github/workflows/`:

### 1. Continuous Integration (`ci.yml`)
- Triggered on push / pull request to `main`.
- Runs full Python pytest suite (`pytest target_service/ worker/ cli/ backend/`).
- Validates Node.js 20 React frontend compilation (`npm run build`).
- Validates Dockerfile builds for Backend, Worker, Frontend, and Target Service.

### 2. Continuous Delivery & GHCR Publishing (`deploy.yml`)
- Publishes immutable Docker images tagged with Git commit SHA to **GitHub Container Registry (`ghcr.io`)** using the automated `${{ secrets.GITHUB_TOKEN }}`.
- Launches multi-container environment with dynamic deployment metadata (`COMMIT_SHA`, `APPLICATION_VERSION`, `BUILD_TIMESTAMP`).
- Executes [`scripts/deploy.py`](file:///D:/Projects/Sceptic/scripts/deploy.py) to evaluate Trust Gate recommendation, probe `/health`, and verify running commit SHA before updating deployment status to `ACTIVE`.

---

## 11. Configuration & Environment Variables

Stored in `.env` (copy from [`.env.example`](file:///D:/Projects/Sceptic/.env.example)):

```bash
# Database Configuration
DATABASE_URL=postgresql+asyncpg://sceptic:sceptic_password_dev@localhost:5432/sceptic

# Redis & Celery
REDIS_URL=redis://localhost:6379/0
REDIS_PORT=6379

# Service Ports
BACKEND_PORT=8000
FRONTEND_PORT=5173
TARGET_SERVICE_PORT=8080
PROMETHEUS_PORT=9090
GRAFANA_PORT=3000

# Target Deployment Metadata
APPLICATION_VERSION=1.0.0
COMMIT_SHA=dev-local
BUILD_TIMESTAMP=2026-10-07T00:00:00Z
ENVIRONMENT=development

# AI / LLM Configuration (Optional - falls back to deterministic AST)
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=openai/gpt-oss-120b

# Security & Tokens
JWT_SECRET_KEY=sceptic-super-secret-dev-jwt-key-32-chars-long!
```

---

## 12. Hands-On Runbook & Troubleshooting

### Running the Entire Platform Locally

#### Option A: Lightweight Native Python (No Docker Required)
```powershell
# 1. Start Backend API (Port 8000)
.\venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000 --reload

# 2. Start Target Application (Port 8080)
.\venv\Scripts\python.exe -m uvicorn target_service.main:app --port 8080 --reload

# 3. Start Frontend Dashboard (Port 5173)
cd frontend
npm run dev
```

#### Option B: Full Multi-Container Docker Stack
```powershell
docker compose up -d
```

### Running Automated Verification Tests
```powershell
# Run the complete test suite (145 tests)
.\venv\Scripts\pytest -q

# Run Phase 15 Rollback Agent tests specifically
.\venv\Scripts\pytest -q backend/test_phase15_rollback.py
```

### Common Troubleshooting

#### 1. Docker Error: `read-only file system` or `input/output error`
- **Cause**: Windows Drive `C:` has less than 5 GB of free space, causing the WSL2 virtual disk (`ext4.vhdx`) to lock in read-only mode.
- **Fix**: Free up 10–15 GB on `C:`, quit Docker Desktop, run `wsl --shutdown` in PowerShell, and restart Docker Desktop. Alternatively, configure Docker Desktop Settings → Resources → Advanced to store the virtual disk on Drive `D:` (which has plenty of space).

#### 2. Redis Celery shows "Unconfigured" in Web Dashboard
- **Cause**: Missing `REDIS_URL` in `.env`.
- **Fix**: Ensure `REDIS_URL=redis://localhost:6379/0` is present in your `.env`. The backend will automatically report `redis_configured: true`.

#### 3. Grafana Dashboard Won't Open (`http://localhost:3000`)
- **Cause**: Docker Desktop is not running.
- **Fix**: Launch Docker Desktop and run `docker compose up -d grafana prometheus`. Grafana will start with anonymous viewer enabled.
