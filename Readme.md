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