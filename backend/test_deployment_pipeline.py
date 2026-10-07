"""
Tests for Phase 11: CI/CD Pipeline, Deployment Automation & Gate Verification.

Verifies:
1. Trust Score deployment gating (APPROVE allowed, BLOCK & REQUEST_CHANGES prevented).
2. Target health and runtime commit SHA verification.
3. Commit SHA mismatch deterministic failure detection.
4. Database state transitions from DEPLOYING -> ACTIVE (success) and DEPLOYING -> FAILED (failure).
5. Workflow YAML structure and required GitHub Actions permissions.
"""

import os
import sys
import yaml
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Ensure root directory on path for scripts import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from database import Base, get_db
import models
import schemas
from auth import create_access_token
from scripts.deploy import evaluate_trust_gate, verify_target_health, run_deployment_pipeline

TEST_DB_URL = "sqlite+aiosqlite:///./test_pipeline_phase11.db"
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


async def create_user_and_project(session: AsyncSession):
    user = models.User(name="DevOps Lead", email="devops@sceptic.io")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    project = models.Project(
        user_id=user.id,
        name="target-app-repo",
        repository_url="https://github.com/org/target-app",
        default_branch="main"
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    token = create_access_token(data={"sub": str(user.id), "email": user.email, "name": user.name})
    return user, project, token


# ========================================================
# 1. TRUST SCORE DEPLOYMENT GATE TESTS (STEP 11)
# ========================================================

def test_trust_score_deployment_gate():
    """Verify deployment gate permits APPROVE and blocks REQUEST_CHANGES and BLOCK."""
    # APPROVE: Deployment allowed
    ok_approve, msg1 = evaluate_trust_gate("APPROVE")
    assert ok_approve is True
    assert "passed" in msg1.lower()

    # REQUEST_CHANGES: Deployment prevented
    ok_rc, msg2 = evaluate_trust_gate("REQUEST_CHANGES")
    assert ok_rc is False
    assert "halted" in msg2.lower()
    assert "REQUEST_CHANGES" in msg2

    # BLOCK: Deployment prevented
    ok_block, msg3 = evaluate_trust_gate("BLOCK")
    assert ok_block is False
    assert "halted" in msg3.lower()
    assert "BLOCK" in msg3

    # Default / None: No gate restriction
    ok_none, _ = evaluate_trust_gate(None)
    assert ok_none is True


# ========================================================
# 2. TARGET HEALTH & COMMIT SHA VERIFICATION TESTS (STEP 12)
# ========================================================

def test_target_health_verification_success():
    """Verify target health check passes when commit SHA matches."""
    mock_health = MagicMock()
    mock_health.status_code = 200
    mock_health.json.return_value = {"status": "healthy"}

    mock_version = MagicMock()
    mock_version.status_code = 200
    mock_version.json.return_value = {
        "version": "1.0.0",
        "commit_sha": "expected-sha-123",
        "environment": "production"
    }

    def mock_get(url):
        if url.endswith("/health"):
            return mock_health
        return mock_version

    with patch("httpx.Client.get", side_effect=mock_get):
        success, v_data, reason = verify_target_health(
            target_url="http://mock-target:8080",
            expected_commit_sha="expected-sha-123",
            timeout_seconds=2.0
        )
        assert success is True
        assert v_data["commit_sha"] == "expected-sha-123"
        assert "passed" in reason.lower()


def test_target_commit_mismatch_failure():
    """Verify target verification fails immediately when running commit does not match expected commit."""
    mock_health = MagicMock()
    mock_health.status_code = 200
    mock_health.json.return_value = {"status": "healthy"}

    mock_version = MagicMock()
    mock_version.status_code = 200
    mock_version.json.return_value = {
        "version": "1.0.0",
        "commit_sha": "stale-old-sha-456",
        "environment": "production"
    }

    def mock_get(url):
        if url.endswith("/health"):
            return mock_health
        return mock_version

    with patch("httpx.Client.get", side_effect=mock_get):
        success, v_data, reason = verify_target_health(
            target_url="http://mock-target:8080",
            expected_commit_sha="new-expected-sha-789",
            timeout_seconds=2.0
        )
        assert success is False
        assert "mismatch" in reason.lower()
        assert "stale-old-sha-456" in reason


# ========================================================
# 3. FULL DEPLOYMENT LIFECYCLE & DATABASE STATE TESTS (STEP 8 & 13)
# ========================================================

from starlette.testclient import TestClient

@pytest.mark.anyio
async def test_successful_deployment_becomes_active():
    """Verify deployment state transitions from DEPLOYING to ACTIVE upon successful verification."""
    async with TestingSessionLocal() as session:
        user, project, token = await create_user_and_project(session)

    test_client = TestClient(app, base_url="http://test")

    # Mock target service to return healthy and matching commit
    mock_health = MagicMock()
    mock_health.status_code = 200
    mock_health.json.return_value = {"status": "healthy"}

    mock_version = MagicMock()
    mock_version.status_code = 200
    mock_version.json.return_value = {
        "version": "1.0.0",
        "commit_sha": "sha-release-100",
        "environment": "production"
    }

    def mock_get(url):
        if url.endswith("/health"):
            return mock_health
        return mock_version

    with patch("httpx.Client.get", side_effect=mock_get):
        exit_code, result = run_deployment_pipeline(
            project_id=str(project.id),
            commit_sha="sha-release-100",
            image_name="ghcr.io/sceptic/target-service",
            image_tag="sha-release-100",
            environment="production",
            target_url="http://test-target:8080",
            backend_url="http://test",
            api_token=token,
            trust_recommendation="APPROVE",
            timeout_seconds=2.0,
            client=test_client
        )

        assert exit_code == 0
        assert result["status"] == "ACTIVE"

        # Verify in Database
        async with TestingSessionLocal() as session:
            res = await session.execute(
                select(models.Deployment).filter(models.Deployment.id == result["deployment_id"])
            )
            dep = res.scalars().first()
            assert dep is not None
            assert dep.status == "ACTIVE"
            assert dep.commit_sha == "sha-release-100"
            assert dep.completed_at is not None


@pytest.mark.anyio
async def test_failed_deployment_becomes_failed():
    """Verify deployment state transitions to FAILED upon health or commit failure (Step 13)."""
    async with TestingSessionLocal() as session:
        user, project, token = await create_user_and_project(session)

    test_client = TestClient(app, base_url="http://test")

    # Mock target service returning HTTP 500 error
    mock_err = MagicMock()
    mock_err.status_code = 500
    mock_err.text = "Internal Server Error"

    with patch("httpx.Client.get", return_value=mock_err):
        exit_code, result = run_deployment_pipeline(
            project_id=str(project.id),
            commit_sha="sha-failing-100",
            image_name="ghcr.io/sceptic/target-service",
            image_tag="sha-failing-100",
            environment="production",
            target_url="http://broken-target:8080",
            backend_url="http://test",
            api_token=token,
            timeout_seconds=1.0,
            client=test_client
        )

        assert exit_code == 1
        assert result["status"] == "FAILED"

        # Verify in Database
        async with TestingSessionLocal() as session:
            res = await session.execute(
                select(models.Deployment).filter(models.Deployment.id == result["deployment_id"])
            )
            dep = res.scalars().first()
            assert dep is not None
            assert dep.status == "FAILED"
            assert dep.commit_sha == "sha-failing-100"


# ========================================================
# 4. GITHUB ACTIONS WORKFLOW VALIDATION (STEP 2 & 14)
# ========================================================

def test_workflow_files_exist_and_valid():
    """Verify that CI and CD workflow files exist and contain valid YAML structure with required permissions."""
    ci_path = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "ci.yml")
    deploy_path = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "deploy.yml")

    assert os.path.exists(ci_path), "ci.yml does not exist"
    assert os.path.exists(deploy_path), "deploy.yml does not exist"

    with open(ci_path, "r", encoding="utf-8") as f:
        ci_yaml = yaml.safe_load(f)
    assert "jobs" in ci_yaml
    assert "test-python-suite" in ci_yaml["jobs"]
    assert "build-frontend" in ci_yaml["jobs"]
    assert "validate-docker" in ci_yaml["jobs"]

    with open(deploy_path, "r", encoding="utf-8") as f:
        deploy_yaml = yaml.safe_load(f)
    assert "permissions" in deploy_yaml
    assert deploy_yaml["permissions"]["packages"] == "write"
    assert deploy_yaml["permissions"]["contents"] == "read"
    assert "publish-and-deploy" in deploy_yaml["jobs"]
