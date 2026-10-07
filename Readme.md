# Sceptic - Independent AI-generated code verification system

This is my Agentic and DevOps Project.

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