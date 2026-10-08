# Sceptic - Independent AI-generated code verification system

This is my Agentic and DevOps Project.

> 📖 **Comprehensive Platform Manual**: For the complete, all-in-one platform guide covering architecture, all verification agents, complete REST API & CLI references, database schema, observability, and runbooks, see [SCEPTIC_APP_GUIDE.md](SCEPTIC_APP_GUIDE.md).

## Phase 1: Skeleton & Plumbing

This phase includes the basic development skeleton and makes all core infrastructure services work together.

### Project Structure
- `backend/` - FastAPI backend application
- `frontend/` - React + Vite + Tailwind application
- `worker/` - (Phase 2) Celery tasks
- `cli/` - (Phase 2) Command-line interface
- `infra/` - Infrastructure configurations
- `.github/` - (Phase 2) CI/CD pipelines
- `docs/` - Documentation

### Prerequisites
- Docker
- Docker Compose

### How to Start the Development Environment
1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
2. Start the services with Docker Compose:
   ```bash
   docker-compose up --build
   ```

### How to Verify Services

- **Backend Health:** Open `http://localhost:8000/health` in your browser. It should return a JSON response confirming status, PostgreSQL, and Redis connections.
- **Frontend-Backend Communication:** Open `http://localhost:5173` in your browser. You should see a "Backend Connection Status" panel showing the JSON response fetched from the backend.

### How to Stop the Services
Press `Ctrl+C` in the terminal where Docker Compose is running, and then run:
```bash
docker-compose down
```

## Phase 2: Database Layer

This phase introduces the foundational database layer using PostgreSQL, SQLAlchemy, and Alembic.

### Database Architecture
- **SQLAlchemy Engine & Session**: Configured in `backend/database.py`.
- **Alembic**: Used for database schema migrations.
- **Pydantic**: Used for API response serialization (`backend/schemas.py`).

### Models and Relationships
- **PullRequest**: Represents a PR being audited. Has a one-to-many relationship with `AuditRun`.
- **AuditRun**: Represents a single execution of Sceptic on a PR. Has a one-to-many relationship with `AgentFinding`.
- **AgentFinding**: Represents an individual finding from an agent (e.g., Fact-Checker).

### Alembic Migration Process
To run database migrations manually:
1. Run `docker compose exec backend bash`
2. Run `alembic upgrade head`

### How to Verify the Database
- Open your browser to `http://localhost:8000/audits`. You should see an empty JSON array `[]` initially, indicating that the `AuditRun` table was queried successfully.

### Testing
To run the automated tests for the database schema and API endpoints:
1. Run `docker compose exec backend bash`
2. Run `pytest test_api.py`

### Note on Future Phases
Agents, auditing logic, Celery workers, CLI, CI/CD, and the React dashboard are **NOT** implemented in this phase and will be added in Phase 3+.

## Phase 3: Fact-Checker Agent

This phase implements the deterministic API verification tool and its minimal CrewAI Agent wrapper. 

### Fact-Checker Architecture
- **Tool (`worker/fact_checker.py`)**: Uses Python's `ast` module to statically parse source code. It resolves module names, attempts to dynamically load them via `importlib`, and verifies function existence and signature parameters using `dir()` and `inspect.signature()`.
- **CrewAI Wrapper (`worker/crewai_wrapper.py`)**: Encapsulates the deterministic tool inside a CrewAI Agent. The LLM does **not** guess API correctness; it strictly delegates to the tool and formats the structured findings.

### Finding Status Types
- **VALID**: The API call and parameters were confirmed to exist in the environment.
- **INVALID**: The function does not exist, or required/keyword parameters mismatch the real signature.
- **UNRESOLVED**: The code is too dynamic to resolve statically (e.g., calling a method on an unknown object variable).

### Testing the Fact-Checker
You can run the pure AST verification unit tests without needing an LLM key:
```bash
pytest worker/test_fact_checker.py
```

### Running the Standalone CrewAI Test
To see the Fact-Checker Agent in action (requires an LLM API Key like `OPENAI_API_KEY` in your `.env`):
```bash
python worker/test_crewai.py
```

## Phase 4: Blind Tester + Security Guard Agents

Phase 4 introduces two independent verification agents: the specification-driven **Blind Tester** and the hybrid deterministic/LLM **Security Guard**.

---

### Part A: Blind Tester Agent

#### Purpose
The Blind Tester generates unbiased, specification-based unit tests to verify whether code fulfills its functional requirements.

#### Information-Isolation Principle (Architectural Requirement)
The test-generation LLM **must never see the implementation** it is testing.
- **Allowed Inputs**: Function name, docstring, specification / PR description, approved specification metadata.
- **Prohibited Inputs**: Function body / implementation code, existing test suites, findings from other agents (Fact-Checker, Security Guard).
- **Enforcement**: Validated in code via `SpecificationMetadata.validate_isolation()`. Passing prohibited fields raises a `ValueError`.

#### Test Generation
- Powered by **Groq LLM** (`llama-3.3-70b-versatile`).
- Generates executable `pytest` test suites covering normal behavior, boundary/edge conditions, and invalid inputs based strictly on docstrings and specifications.
- Includes deterministic fallback generation when offline or no API key is set.

#### Test Execution & Finding Generation
- Tests run in an isolated execution sandbox against the real implementation.
- Captures test results (`passed`, `failed`, `errors`).
- Failures are transformed into structured findings conforming to the `AgentFinding` schema (`severity: HIGH`, failure description, line/test name, traceback evidence).

#### Limitations
- Functions requiring external state (databases, remote network APIs) require mocked fixtures or explicit environmental preconditions in their specifications.

---

### Part B: Security Guard Agent

#### Hybrid Architecture
```
Target Code
    │
┌───┴───────────┐
│               │
▼               ▼
Semgrep       Bandit
│               │
└───┬───────────┘
    ▼
Normalized Security Findings
    ▼
Groq Contextual Analysis (Validation & Exploitability)
    ▼
Final Structured Security Findings
```

#### Roles of Deterministic Scanners
- **Semgrep**: Static analysis enforcing AST/pattern rules for dangerous shell execution (`subprocess`, `os.system`), dangerous `eval`/`exec`, insecure deserialization (`pickle`), and hardcoded secrets.
- **Bandit**: Dedicated Python AST security scanner detecting common vulnerability patterns (B105/B106 secrets, B307 eval, etc.).

#### Result Normalization & Evidence Preservation
- Scanner outputs are mapped to the unified `AgentFinding` database schema (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`).
- **Original scanner evidence** (rule IDs, line numbers, code snippets) is **never discarded or fabricated**.

#### Groq Contextual Analysis
- Groq evaluates the scanner findings in the context of the code to determine true positives vs. false positives, explain exploit scenarios, and suggest remediations.
- **Graceful Fallback**: If the LLM is unavailable or fails, deterministic scanner evidence is preserved untouched.

#### Limitations
- Static analysis cannot detect runtime-only business logic vulnerabilities or vulnerabilities in uninspected dynamic dependencies.

---

### Running Phase 4 Tests
```bash
# Run Blind Tester unit tests & information isolation validation
pytest worker/test_blind_tester.py -v

# Run Security Guard static scanner and contextual analyzer tests
pytest worker/test_security_guard.py -v

# Run standalone CrewAI agent wrapper tests
pytest worker/test_phase4_crewai.py -v
```

## Phase 5: Agent Orchestration and End-to-End Audit Pipeline

Phase 5 integrates the three independent verification agents into an asynchronous, production-ready audit pipeline.

```
Webhook (GitHub PR Event)
         │
         ▼
FastAPI (/webhook) ───[Idempotency Check]───► PostgreSQL (PullRequest, AuditRun)
         │
         ▼
   Celery Task (Queue via Redis)
         │
         ▼
Audit Orchestrator (Fan-Out / Fan-In)
    ┌────┴─────────────────────────────┐
    ▼                                  ▼                                  ▼
Fact-Checker Agent           Blind-Tester Agent (ISOLATED)     Security-Guard Agent
(AST, inspect, dir)          (Docstring/Spec ONLY)             (Semgrep, Bandit, Groq)
    │                                  │                                  │
    └──────────────────────────────────┼──────────────────────────────────┘
                                       ▼
                              Report Synthesizer (Fan-In)
                                       │
                                       ▼
                             Deterministic Trust Score
                                       │
                                       ▼
                       PostgreSQL (Findings, Final Score)
```

### 1. Webhook Flow & Idempotency
- **Endpoint**: `POST /webhook`
- Accepts GitHub pull request events or standard JSON payload (`repository`, `pr_number`, `commit_sha`, `branch_name`).
- **Idempotency**: Repeated webhooks for the exact same `commit_sha` and `pr_number` return `HTTP 200 (ALREADY_EXISTS)` without triggering duplicate audits.
- Creates `PullRequest` and `AuditRun` (`status: PENDING`), then immediately enqueues the Celery background task and returns `HTTP 202 ACCEPTED`.

### 2. Celery & Redis Role
- **Broker & Backend**: Redis (`REDIS_URL`).
- **Task**: `execute_audit_pipeline(audit_run_id, payload)`
- Transitions `AuditRun` state: `PENDING` -> `RUNNING` -> `COMPLETED` (or `FAILED` on unhandled error, preventing zombie states).
- Persists all `AgentFinding` records and saves the computed `trust_score`, `summary`, and `recommendation` to PostgreSQL.

### 3. CrewAI Fan-Out / Fan-In Orchestration
- **Fan-Out**: Fact-Checker, Blind-Tester, and Security-Guard execute independently in parallel.
- **Information Isolation**: Blind Tester receives *only* specification metadata (function name, docstring, PR description). The implementation code is isolated to the sandbox executor and never enters the LLM generation context.
- **Fault-Tolerant Execution**: A failure in one agent (e.g., scanner error) records a diagnostic finding while permitting the remaining agents to complete.

### 4. Deterministic Trust Score Methodology
The Trust Score evaluates verification evidence through an objective, deterministic formula:
- **Starting Score**: 100 points
- **Deductions**:
  - `CRITICAL` severity: **-35 points** (Remote code execution, command injection)
  - `HIGH` severity: **-20 points** (Specification failure, non-existent API)
  - `MEDIUM` severity: **-10 points** (Invalid keyword parameter, security warning)
  - `LOW` severity: **-3 points** (Informational security notice)
  - `UNRESOLVED / ERROR`: **-5 points** (Dynamic ambiguity or scanner execution error)
- **Score Range**: Clamped to `[0, 100]`.
- **Recommendation Thresholds**:
  - `85 - 100`: **APPROVE** (High confidence, requirements fulfilled)
  - `65 - 84`: **REQUEST_CHANGES** (Minor issues or warnings present)
  - `0 - 64`: **BLOCK** (Critical vulnerabilities or specification violations)

### 5. Running Phase 5 Tests
```bash
# Run Phase 5 orchestration, webhook, Celery, and end-to-end flow tests:
pytest worker/test_phase5_orchestration.py -v

# Run the complete test suite across all phases (37 tests):
pytest backend/test_api.py worker/test_fact_checker.py worker/test_blind_tester.py worker/test_security_guard.py worker/test_phase4_crewai.py worker/test_phase5_orchestration.py -v
```

---

## Phase 6: Command-Line Interface (CLI)

Phase 6 implements the **Typer + Rich** command-line interface. Developers and CI workflows can run synchronous, in-process Sceptic audits against files and directories directly from the terminal without routing through HTTP or Celery.

### Architecture

```
CLI (Typer + Rich) ─────────┐
FastAPI Webhook ────────────┼──► Shared AuditService (In-Process / Celery) ──► AuditOrchestrator
Celery Worker ──────────────┘
```

The CLI reuses the underlying verification agents (`Fact-Checker`, `Blind Tester`, `Security Guard`, `Report Synthesizer`, and deterministic `Trust Score`) via a shared audit service (`worker/audit_service.py`) without duplicating agent logic.

### Commands & Options

```bash
# General help
sceptic --help

# Audit command help
sceptic audit --help

# Audit a single Python file
sceptic audit path/to/script.py

# Audit an entire project directory
sceptic audit path/to/project/

# Audit with detailed evidence snippets
sceptic audit path/to/script.py --verbose

# Output machine-readable JSON for CI integration
sceptic audit path/to/script.py --json
```

### Exit Codes

| Exit Code | Meaning | Condition |
|:---|:---|:---|
| **`0`** | **SUCCESS** | Code approved (`APPROVE` recommendation, Trust Score >= 85). |
| **`1`** | **AUDIT FAILURE** | Verification issues detected (`REQUEST_CHANGES` or `BLOCK`, Trust Score < 85). |
| **`2`** | **CLI ERROR** | Invalid path, non-Python file, permission error, or runtime error. |

### Terminal Display Features
- **Live Spinner**: Clean in-process progress indicators during agent execution.
- **Agent Status Table**: Status and count of findings contributed by Fact-Checker, Blind-Tester, and Security-Guard.
- **Severity Breakdown**: Visual distribution across CRITICAL, HIGH, MEDIUM, LOW, and UNRESOLVED findings.
- **Findings Table**: Detailed table listing severity, originating agent, title, file:line location, and description.
- **Evidence Snippets (`-v`)**: Formatted panels displaying line-by-line evidence and test traces.
- **Verdict Panel**: Prominently displays the final Trust Score (`/100`), Recommendation (`APPROVE`, `REQUEST_CHANGES`, `BLOCK`), and synthesized summary.

### Testing Phase 6
```bash
# Run CLI test suite (9 tests)
pytest cli/test_cli.py -v

# Run complete project test suite across all phases (48 tests)
pytest backend/test_api.py worker/ cli/ -v
```

---

## Phase 7: React Dashboard + Documentation Center

Phase 7 implements the developer-facing **React + Vite + TypeScript + TailwindCSS** web dashboard powered by **TanStack Query**, coupled with an in-app **Documentation Center**.

### Frontend Architecture
- **State Management**: TanStack Query (`@tanstack/react-query`) handles caching, auto-refetching, and network states.
- **Single-Page Navigation**:
  - `Dashboard`: Real-time audit metrics, average trust score, findings breakdown, and recent audit activity.
  - `Audits`: Filterable and searchable repository of all pull requests and in-process audits.
  - `Audit Details`: Granular breakdown of agent findings, evidence traces, and synthesizer assessment.
  - `Findings`: Filter by severity (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) and agent (`Fact-Checker`, `Blind-Tester`, `Security-Guard`).
  - `Documentation`: 19-section interactive developer guide and CLI installation manual.
- **Backend Endpoints Consumed**:
  - `GET /health`: Database and Redis connectivity monitoring.
  - `GET /audits`: Paginated list of audit runs.
  - `GET /audits/{id}`: Detailed single audit record with full findings and pull request metadata.

### How to Run the Dashboard
```bash
cd frontend
npm install
npm run dev
# Dashboard is available at http://localhost:5173
```

---

## Phase 9: Deployment & DevOps Foundation

Phase 9 establishes the multi-container deployment architecture for Sceptic and provides an independent target service for future post-deployment DevOps agents.

### Containerized Topology
- **Sceptic Backend**: FastAPI application with database health endpoints on port `8000`.
- **Sceptic Celery Worker**: Dedicated container executing background audit workflows.
- **Sceptic Frontend**: React/Vite dashboard on port `5173`.
- **Redis**: Celery message broker and result backend on port `6380:6379`.
- **PostgreSQL**: Local container database with persistent volume and external Supabase fallback.
- **Target Application**: Independent deployable service on port `8080` exposing `/health`, `/version`, and `/api/demo`.

### Quickstart with Docker Compose
```bash
# Start development stack (6 services)
docker compose up --build

# Or run the production profile with structured log rotation
docker compose -f infra/docker-compose.prod.yml up -d --build
```

See [docs/deployment.md](docs/deployment.md) for full deployment architecture and configuration details.

---

## Phase 10: Deployment State & Database

Phase 10 implements the persistent relational database state and API layer required for post-deployment monitoring, configuration drift detection, and automated rollback recovery.

### Relational Schema Hierarchy
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

### Models & Observability Entities
- **Deployment**: Core record for application releases, image tags, commit SHAs, and statuses (`PENDING`, `DEPLOYING`, `ACTIVE`, `FAILED`, `ROLLED_BACK`).
- **TelemetrySnapshot**: Captures timestamped health and performance observations (`request_count`, `error_rate`, `latency_avg`, `latency_p95`).
- **DriftEvent**: Captures configuration, commit, or container image deviations (`expected_value` vs `actual_value`).
- **RollbackRecord**: Records recovery operations and target fallback deployments with safety check validations.

### Database Migrations
Run the latest database schema migrations via Alembic:
```bash
alembic upgrade head
```

Verify migration heads:
```bash
alembic heads
# Expected: a7d8e9f01234 (head)
```

---

## Phase 11: CI/CD Pipeline + GHCR + Automated Deployment

Phase 11 introduces GitHub Actions workflows for continuous integration, Docker image publishing to GitHub Container Registry (GHCR), and automated health-verified deployment.

### Workflows
- **CI Workflow (`.github/workflows/ci.yml`)**:
  - Python test matrix covering Backend, Worker, CLI, and Target Service.
  - Frontend React/Vite/TypeScript build validation.
  - Docker Compose syntax and multi-container build verification.
- **CD & Publishing Workflow (`.github/workflows/deploy.yml`)**:
  - Packages and publishes Docker images to GHCR (`ghcr.io/<owner>/sceptic-<service>:<commit-sha>` and `:latest`).
  - Launches container stack with runtime metadata (`COMMIT_SHA`, `APPLICATION_VERSION`, `ENVIRONMENT`).
  - Executes deployment gating (`APPROVE` allowed, `BLOCK`/`REQUEST_CHANGES` prevented).
  - Validates container readiness (`/health`), runtime metadata (`/version`), and commit identity.
  - Records final deployment state in PostgreSQL (`DEPLOYING` $\to$ `ACTIVE` or `FAILED`).

---

## Phase 12: Observability Foundation (Prometheus + Grafana)

Phase 12 establishes the foundational timeseries telemetry layer required by future post-deployment agents (such as Pipeline Watchdog).

### Architecture & Capabilities
- **Prometheus Service (`prom/prometheus:v2.51.0`)**: Scrapes the FastAPI target service every 5 seconds at `target-service:8080/metrics`.
- **Target Application Instrumentation**:
  - `GET /metrics`: Standard Prometheus scrapable metrics endpoint.
  - `http_requests_total`: Request counter tagged with `method`, `endpoint`, and `status_code`.
  - `http_request_duration_seconds`: Latency histogram with 11 buckets.
  - `http_requests_in_progress`: In-flight active request gauge.
  - `target_service_app_info`: Release metadata (`version`, `commit_sha`, `build_timestamp`, `environment`).
  - `GET /api/fail?code=500`: Simulated failure endpoint for verifying 5xx telemetry response.
- **Grafana Service (`grafana/grafana:10.4.0`)**:
  - Automatically provisions Prometheus datasource via internal Docker network (`http://prometheus:9090`).
  - Automatically loads the **Sceptic - Target Service Observability** dashboard with 8 real panels:
    - Target Health (Up status)
    - Total Requests
    - In-Progress Active Requests
    - Error Rate %
    - Release Metadata (Version, SHA, Env)
    - Request Rate (Throughput)
    - Response Latency (p95)
    - HTTP Status Code Distribution
- **Accessing Observability**:
  - Prometheus UI: `http://localhost:9090`
  - Grafana Dashboard: `http://localhost:3000` (Anonymous Viewer enabled)

---

## Phase 13: Pipeline Watchdog + Deployment Gatekeeper

Phase 13 introduces dedicated post-deployment verification components ensuring runtime health and deployment integrity without automated rollback.

### Components & Capabilities
- **Pipeline Watchdog (`backend/watchdog.py`)**:
  - Validates live `/health` status and response codes with strict timeout handling.
  - Queries Prometheus metrics (`http_requests_total`, `http_request_duration_seconds`) to calculate error rates and p95 latency.
  - Applies minimum-sample threshold protection (`WATCHDOG_MIN_REQUESTS`) to eliminate false alerts on sparse traffic.
  - Accurately tracks Prometheus availability and metric absence as explicit `UNRESOLVED` states rather than false passes.
  - Detects `DEPLOYMENT_CORRELATED_ANOMALY` when anomalies occur following release events.
  - Persists real runtime telemetry observations to `telemetry_snapshots`.
- **Deployment Gatekeeper (`backend/gatekeeper.py`)**:
  - Deterministically verifies expected `commit_sha` against running commit via `/version`.
  - Verifies application version and environment alignment.
  - Detects image digest drift when digests are provided, safely reporting `UNRESOLVED` when digest metadata is unavailable.
  - Verifies database deployment state consistency (`DEPLOYMENT_STATE_MISMATCH`).
  - Idempotently records configuration deviations in `drift_events` without duplicate explosion.
- **REST APIs**:
  - `POST /deployments/{id}/watchdog/check`: Trigger runtime behavior verification.
  - `POST /deployments/{id}/gatekeeper/check`: Trigger deployment integrity verification.
  - `GET /deployments/{id}/telemetry`: Query historical telemetry snapshots.
  - `GET /deployments/{id}/drift-events`: Query recorded drift events.
- **CLI Commands**:
  - `sceptic status`: Displays deployment, runtime health, error rate, p95 latency, and drift summary.
  - `sceptic watchdog [id]`: On-demand Watchdog verification from CLI.
  - `sceptic gatekeeper [id]`: On-demand Gatekeeper verification from CLI.

---

## Phase 15: Rollback Agent (Deployment Recovery Engine)

Phase 15 implements the **Rollback Agent**, an autonomous recovery engine that safely, idempotently, and auditably recovers from failed deployments or critical configuration drift.

### Recovery Workflow & Safety Controller
1. **Decision Validation**:
   - Rejects rollback if the target deployment is already marked `ROLLED_BACK`.
   - Requires non-empty operational justification.
2. **Previous Known-Good Discovery**:
   - Locates predecessor deployment via explicit request, `previous_deployment_id`, or chronological search for prior healthy deployments.
   - Strictly enforces project-level tenancy boundaries.
3. **Mandatory Pre-Flight Safety Checks**:
   - Target deployment validity & identity.
   - Environment compatibility (prevents deploying staging images to production).
   - Container image metadata and repository availability.
   - Database schema migration safety (guards against incompatible downgrades).
   - Concurrency lock guard (prevents race conditions with active rollbacks).
4. **Abort Guard**:
   - If any safety check fails, recovery halts immediately.
   - Persists an `ABORTED` audit record to `rollback_records` without mutating the running system.
5. **Execution & Health Verification**:
   - Acquires the project rollback lock (`status=IN_PROGRESS`).
   - Dispatches execution to the container recovery executor.
   - Waits for service stabilization and verifies `/health` (HTTP 200).
   - Verifies runtime commit SHA via `/version` against target deployment metadata.
   - Aligns state: current deployment set to `ROLLED_BACK`, target deployment set to `ACTIVE`, active drift events marked resolved.
   - Persists final `SUCCESS` or `FAILED` audit record with full diagnostics.

### REST APIs
- `POST /deployments/{id}/rollback`: Trigger controlled recovery operation.
- `POST /deployments/{id}/rollback/check`: Dry-run pre-flight safety evaluation.
- `GET /deployments/{id}/rollbacks`: List historical rollback audit records.

### CLI Commands
- `sceptic rollback [deployment_id] [--target <id>] [--reason <text>]`: Execute rollback from CLI.
- `sceptic rollback [deployment_id] --dry-run`: Evaluate pre-flight safety checks in terminal without executing.