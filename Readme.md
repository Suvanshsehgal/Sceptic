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

### Note on Future Phases
Agents, auditing, Celery workers, CLI, CI/CD, and database models are **NOT** implemented in this phase and will be added in Phase 2.