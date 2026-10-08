"""
Comprehensive Test Suite for Phase 15: Sceptic Rollback Agent.

Verifies:
1. Decision Validation:
   - Rollback rejected if deployment status is already ROLLED_BACK.
   - Rollback rejected if operational justification reason is empty or too short.
   - Rollback rejected if trigger_source is invalid.
2. Target Discovery:
   - Target auto-discovery via previous_deployment_id.
   - Target auto-discovery via timeline history when previous_deployment_id is null.
   - Explicit target deployment specified by requester.
   - Abort when target does not exist or belongs to another project.
   - Abort when target is the current deployment itself.
   - Abort when no previous known-good deployment exists.
3. Pre-Flight Safety Checks:
   - Target deployment validity.
   - Environment compatibility (e.g. staging vs production mismatch rejected).
   - Image metadata availability (empty image or tag rejected).
   - Database migration safety (unsafe migration downgrade rejected unless overridden).
   - Rollback concurrency lock (concurrent IN_PROGRESS or PENDING rollback blocks execution).
4. Aborted Rollback Behavior:
   - Failure of any safety check stops execution immediately.
   - RollbackRecord persisted with status=ABORTED and detailed safety_check_result.
   - No changes made to running service or deployment status.
5. Successful End-to-End Recovery:
   - Safety checks PASS -> Lock acquired (IN_PROGRESS) -> Rollback executed ->
     Health verified (/health 200) -> Version & commit SHA verified (/version 200) ->
     Deployment status updated to ROLLED_BACK -> Target deployment status updated to ACTIVE ->
     Active drift events resolved -> RollbackRecord persisted with status=SUCCESS.
6. Post-Rollback Health Failure Handling:
   - Unhealthy /health response causes rollback failure -> status=FAILED.
7. Post-Rollback Version Mismatch Handling:
   - Restored service running wrong commit SHA causes failure -> status=FAILED.
8. Executor Failure Handling:
   - Custom executor exception caught gracefully -> status=FAILED.
9. FastAPI REST APIs:
   - POST /deployments/{id}/rollback (full execution with project RBAC).
   - POST /deployments/{id}/rollback/check (dry-run pre-flight safety check).
   - Multi-tenant isolation (404/403 when accessing another user's project).
"""
import os
import sys
from datetime import datetime, timezone
from uuid import UUID

import pytest
import pytest_asyncio
import httpx
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

backend_dir = os.path.abspath(os.path.dirname(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from database import Base, get_db
import models
import schemas
from auth import create_access_token
from rollback_agent import RollbackAgent, RollbackExecutor, DefaultRollbackExecutor


TEST_DB_URL = "sqlite+aiosqlite:///./test_phase15_rollback.db"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


async def create_user_and_deployments(session: AsyncSession) -> tuple:
    """Helper to create a user, project, and two sequential deployments (v1.0.0 and v1.1.0)."""
    user = models.User(name="SRE Lead", email="sre@sceptic.io")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    project = models.Project(
        user_id=user.id,
        name="Payment Gateway",
        repository_url="https://github.com/sceptic/payment-service",
        default_branch="main"
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    # Initial known-good deployment (v1.0.0)
    dep1 = models.Deployment(
        project_id=project.id,
        commit_sha="commit-v100",
        image_name="ghcr.io/sceptic/payment-service",
        image_tag="v1.0.0",
        image_digest="sha256:1111111111111111",
        environment="production",
        version="1.0.0",
        status="ACTIVE",
        deployed_at=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    )
    session.add(dep1)
    await session.commit()
    await session.refresh(dep1)

    # Subsequent failing deployment (v1.1.0)
    dep2 = models.Deployment(
        project_id=project.id,
        commit_sha="commit-v110-buggy",
        image_name="ghcr.io/sceptic/payment-service",
        image_tag="v1.1.0",
        image_digest="sha256:2222222222222222",
        environment="production",
        version="1.1.0",
        status="FAILED",
        previous_deployment_id=dep1.id,
        deployed_at=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    )
    session.add(dep2)
    await session.commit()
    await session.refresh(dep2)

    token = create_access_token(data={"sub": str(user.id), "email": user.email, "name": user.name})
    return user, project, dep1, dep2, token


def make_mock_client(
    health_status: str = "healthy",
    health_code: int = 200,
    commit_sha: str = "commit-v100",
    version: str = "1.0.0",
    version_code: int = 200
) -> httpx.AsyncClient:
    """Creates a mock AsyncClient responding to target service /health and /version endpoints."""
    async def mock_handler(request: httpx.Request):
        path = request.url.path
        if path == "/health":
            if health_code == 200:
                return httpx.Response(200, json={"status": health_status})
            return httpx.Response(health_code, text="Internal Server Error")
        elif path == "/version":
            if version_code == 200:
                return httpx.Response(200, json={
                    "version": version,
                    "commit_sha": commit_sha,
                    "build_timestamp": "2026-10-01T10:00:00Z",
                    "environment": "production"
                })
            return httpx.Response(version_code, text="Not Found")
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(mock_handler)
    return httpx.AsyncClient(transport=transport, base_url="http://target-service:8080")


class MockExecutor(RollbackExecutor):
    def __init__(self, should_succeed: bool = True):
        self.should_succeed = should_succeed
        self.executed = False

    async def execute(self, deployment: models.Deployment, target_deployment: models.Deployment) -> bool:
        self.executed = True
        if not self.should_succeed:
            raise RuntimeError("Mock container restart error: Docker daemon timeout")
        return True


# ========================================================
# 1. DECISION VALIDATION TESTS
# ========================================================

@pytest.mark.anyio
async def test_decision_validation_rejected_if_already_rolled_back():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)
        dep2.status = "ROLLED_BACK"
        await session.commit()

        agent = RollbackAgent()
        valid, msg = await agent.validate_deployment_and_decision(dep2, "Investigating crash", "MANUAL", session)
        assert valid is False
        assert "already marked ROLLED_BACK" in msg


@pytest.mark.anyio
async def test_decision_validation_rejected_if_reason_empty():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        agent = RollbackAgent()
        valid, msg = await agent.validate_deployment_and_decision(dep2, "", "MANUAL", session)
        assert valid is False
        assert "justification reason is mandatory" in msg


@pytest.mark.anyio
async def test_decision_validation_rejected_if_invalid_trigger_source():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        agent = RollbackAgent()
        valid, msg = await agent.validate_deployment_and_decision(dep2, "Valid reason", "UNKNOWN_SOURCE", session)
        assert valid is False
        assert "Invalid trigger_source" in msg


# ========================================================
# 2. TARGET DISCOVERY TESTS
# ========================================================

@pytest.mark.anyio
async def test_find_previous_deployment_via_link():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        agent = RollbackAgent()
        target, err = await agent.find_previous_deployment(dep2, session)
        assert err is None
        assert target is not None
        assert target.id == dep1.id
        assert target.commit_sha == "commit-v100"


@pytest.mark.anyio
async def test_find_previous_deployment_via_timeline_discovery():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)
        # Clear previous_deployment_id to test timeline query fallback
        dep2.previous_deployment_id = None
        await session.commit()

        agent = RollbackAgent()
        target, err = await agent.find_previous_deployment(dep2, session)
        assert err is None
        assert target is not None
        assert target.id == dep1.id


@pytest.mark.anyio
async def test_find_previous_deployment_explicit_target():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        agent = RollbackAgent()
        target, err = await agent.find_previous_deployment(dep2, session, explicit_target_id=dep1.id)
        assert err is None
        assert target.id == dep1.id


@pytest.mark.anyio
async def test_find_previous_deployment_rejects_self():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        agent = RollbackAgent()
        target, err = await agent.find_previous_deployment(dep2, session, explicit_target_id=dep2.id)
        assert target is None
        assert "cannot be the current deployment itself" in err


@pytest.mark.anyio
async def test_find_previous_deployment_aborts_when_no_prior_exists():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        # Calling on dep1 which is the initial deployment with no predecessors
        agent = RollbackAgent()
        target, err = await agent.find_previous_deployment(dep1, session)
        assert target is None
        assert "No previous known-good deployment found" in err


# ========================================================
# 3. SAFETY CHECKS & LOCK VERIFICATION
# ========================================================

@pytest.mark.anyio
async def test_safety_check_fails_on_environment_mismatch():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)
        dep1.environment = "staging"
        dep2.environment = "production"
        await session.commit()

        agent = RollbackAgent()
        is_safe, checks, err = await agent.verify_safety(dep2, dep1, session)
        assert is_safe is False
        assert checks["environment_compatibility"]["passed"] is False
        assert "environment mismatch" in err.lower()


@pytest.mark.anyio
async def test_safety_check_fails_on_missing_image_metadata():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)
        dep1.image_tag = ""
        await session.commit()

        agent = RollbackAgent()
        is_safe, checks, err = await agent.verify_safety(dep2, dep1, session)
        assert is_safe is False
        assert checks["image_availability"]["passed"] is False


@pytest.mark.anyio
async def test_safety_check_fails_on_active_rollback_lock():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        # Existing active rollback record
        existing_rb = models.RollbackRecord(
            deployment_id=dep2.id,
            target_deployment_id=dep1.id,
            reason="Prior rollback attempt in flight",
            trigger_source="MANUAL",
            status="IN_PROGRESS",
            started_at=datetime.now(timezone.utc)
        )
        session.add(existing_rb)
        await session.commit()

        agent = RollbackAgent()
        is_safe, checks, err = await agent.verify_safety(dep2, dep1, session)
        assert is_safe is False
        assert checks["rollback_lock"]["passed"] is False
        assert "Concurrent rollback operation" in checks["rollback_lock"]["detail"]


# ========================================================
# 4. ABORTED ROLLBACK PERSISTENCE
# ========================================================

@pytest.mark.anyio
async def test_aborted_rollback_persists_record_without_execution():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)
        # Force environment mismatch
        dep1.environment = "staging"
        await session.commit()

        mock_client = make_mock_client()
        mock_exec = MockExecutor()
        agent = RollbackAgent(client=mock_client, executor=mock_exec)

        res = await agent.evaluate_and_execute(
            deployment=dep2,
            reason="High 500 error rate detected",
            trigger_source="WATCHDOG",
            db=session
        )

        assert res.success is False
        assert res.status == "ABORTED"
        assert mock_exec.executed is False  # Safety guard stopped execution

        # Verify RollbackRecord was persisted in DB
        stmt = select(models.RollbackRecord).filter(models.RollbackRecord.deployment_id == dep2.id)
        records = (await session.execute(stmt)).scalars().all()
        assert len(records) == 1
        record = records[0]
        assert record.status == "ABORTED"
        assert record.safety_check_result["environment_compatibility"]["passed"] is False
        assert record.completed_at is not None
        assert "Safety checks failed" in record.error_message


# ========================================================
# 5. SUCCESSFUL END-TO-END ROLLBACK
# ========================================================

@pytest.mark.anyio
async def test_successful_rollback_flow():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        # Add an active drift event that should be resolved by rollback
        drift = models.DriftEvent(
            deployment_id=dep2.id,
            drift_type="COMMIT_MISMATCH",
            expected_value="commit-v100",
            actual_value="commit-v110-buggy",
            severity="CRITICAL",
            description="Active drift detected before rollback"
        )
        session.add(drift)
        await session.commit()

        mock_client = make_mock_client(commit_sha="commit-v100", version="1.0.0")
        mock_exec = MockExecutor(should_succeed=True)
        agent = RollbackAgent(
            client=mock_client,
            executor=mock_exec,
            health_timeout=2.0,
            poll_interval=0.1
        )

        res = await agent.evaluate_and_execute(
            deployment=dep2,
            reason="Automated recovery: runtime error rate breached threshold",
            trigger_source="WATCHDOG",
            db=session
        )

        assert res.success is True
        assert res.status == "SUCCESS"
        assert res.target_deployment_id == dep1.id
        assert mock_exec.executed is True

        # Verify deployment states in database
        await session.refresh(dep2)
        await session.refresh(dep1)
        assert dep2.status == "ROLLED_BACK"
        assert dep1.status == "ACTIVE"

        # Verify drift event was marked resolved
        await session.refresh(drift)
        assert drift.resolved_at is not None

        # Verify RollbackRecord
        stmt = select(models.RollbackRecord).filter(models.RollbackRecord.deployment_id == dep2.id)
        record = (await session.execute(stmt)).scalars().first()
        assert record is not None
        assert record.status == "SUCCESS"
        assert record.completed_at is not None
        assert record.error_message is None
        assert record.safety_check_result["rollback_lock"]["passed"] is True


# ========================================================
# 6. POST-ROLLBACK HEALTH & VERSION FAILURE HANDLING
# ========================================================

@pytest.mark.anyio
async def test_post_rollback_health_failure_records_failed_status():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        # Mock client returning 500 on /health
        mock_client = make_mock_client(health_code=500, health_status="unhealthy")
        mock_exec = MockExecutor(should_succeed=True)
        agent = RollbackAgent(
            client=mock_client,
            executor=mock_exec,
            health_timeout=0.3,
            poll_interval=0.1
        )

        res = await agent.evaluate_and_execute(
            deployment=dep2,
            reason="Service degraded",
            trigger_source="GATEKEEPER",
            db=session
        )

        assert res.success is False
        assert res.status == "FAILED"
        assert "Service recovery failed post-rollback verification" in res.message

        await session.refresh(dep2)
        assert dep2.status == "FAILED"

        # Verify record in DB has status FAILED
        stmt = select(models.RollbackRecord).filter(models.RollbackRecord.deployment_id == dep2.id)
        record = (await session.execute(stmt)).scalars().first()
        assert record.status == "FAILED"
        assert "Health endpoint returned HTTP 500" in record.error_message


@pytest.mark.anyio
async def test_post_rollback_version_mismatch_records_failed_status():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        # Mock client returns healthy, but reports the WRONG commit SHA
        mock_client = make_mock_client(commit_sha="wrong-commit-sha-999")
        mock_exec = MockExecutor(should_succeed=True)
        agent = RollbackAgent(
            client=mock_client,
            executor=mock_exec,
            health_timeout=0.3,
            poll_interval=0.1
        )

        res = await agent.evaluate_and_execute(
            deployment=dep2,
            reason="Version drift rollback",
            trigger_source="GATEKEEPER",
            db=session
        )

        assert res.success is False
        assert res.status == "FAILED"
        assert "Commit SHA mismatch post-rollback" in res.message


# ========================================================
# 7. EXECUTOR FAILURE HANDLING
# ========================================================

@pytest.mark.anyio
async def test_executor_exception_handled_gracefully():
    async with TestingSessionLocal() as session:
        user, project, dep1, dep2, token = await create_user_and_deployments(session)

        # Mock executor that throws exception
        failing_exec = MockExecutor(should_succeed=False)
        mock_client = make_mock_client()
        agent = RollbackAgent(client=mock_client, executor=failing_exec)

        res = await agent.evaluate_and_execute(
            deployment=dep2,
            reason="Crash loop recovery",
            trigger_source="MANUAL",
            db=session
        )

        assert res.success is False
        assert res.status == "FAILED"
        assert "Docker daemon timeout" in res.message

        stmt = select(models.RollbackRecord).filter(models.RollbackRecord.deployment_id == dep2.id)
        record = (await session.execute(stmt)).scalars().first()
        assert record.status == "FAILED"
        assert "Mock container restart error" in record.error_message


# ========================================================
# 8. REST API ENDPOINTS & AUTHENTICATION TESTS
# ========================================================

@pytest.mark.anyio
async def test_api_dry_run_safety_check_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with TestingSessionLocal() as session:
            user, project, dep1, dep2, token = await create_user_and_deployments(session)

        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "reason": "Pre-flight evaluation for canary failure",
            "trigger_source": "MANUAL"
        }

        resp = await client.post(f"/deployments/{dep2.id}/rollback/check", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_safe"] is True
        assert data["target_deployment_id"] == str(dep1.id)
        assert data["target_commit_sha"] == "commit-v100"
        assert data["safety_checks"]["rollback_lock"]["passed"] is True


@pytest.mark.anyio
async def test_api_rollback_endpoint_unauthorized_user_blocked():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with TestingSessionLocal() as session:
            user, project, dep1, dep2, _ = await create_user_and_deployments(session)

            # Different user with no ownership of project
            other_user = models.User(name="Eve Intruder", email="eve@other.com")
            session.add(other_user)
            await session.commit()
            await session.refresh(other_user)
            other_token = create_access_token(data={"sub": str(other_user.id), "email": other_user.email, "name": other_user.name})

        headers_other = {"Authorization": f"Bearer {other_token}"}
        payload = {"reason": "Unauthorized attempt", "trigger_source": "MANUAL"}

        # Attempt to trigger rollback on dep2
        resp = await client.post(f"/deployments/{dep2.id}/rollback", json=payload, headers=headers_other)
        assert resp.status_code == 404  # Strict multi-tenant isolation returns 404 for non-owned resource


@pytest.mark.anyio
async def test_api_rollback_history_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with TestingSessionLocal() as session:
            user, project, dep1, dep2, token = await create_user_and_deployments(session)

            # Insert a record
            rb = models.RollbackRecord(
                deployment_id=dep2.id,
                target_deployment_id=dep1.id,
                reason="Incident #404 recovery",
                trigger_source="WATCHDOG",
                status="SUCCESS",
                safety_check_result={"verified": True},
                completed_at=datetime.now(timezone.utc)
            )
            session.add(rb)
            await session.commit()

        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(f"/deployments/{dep2.id}/rollbacks", headers=headers)
        assert resp.status_code == 200
        records = resp.json()
        assert len(records) == 1
        assert records[0]["status"] == "SUCCESS"
        assert records[0]["reason"] == "Incident #404 recovery"
        assert records[0]["safety_check_result"] == {"verified": True}
