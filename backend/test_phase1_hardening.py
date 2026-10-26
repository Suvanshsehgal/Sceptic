"""
Phase 1 hardening tests: auth, audit ownership, webhook signatures, rollback executor and lock, deploy gate override.
"""
import os
import sys
import hmac
import json
import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from main import app
from database import Base, get_db
import models
import rollback_agent
from rollback_agent import (
    RollbackAgent,
    DefaultRollbackExecutor,
    RollbackExecutorNotConfigured,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from scripts.deploy import evaluate_trust_gate, run_deployment_pipeline

TEST_DB_URL = "sqlite+aiosqlite:///./test_phase1_hardening.db"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, autocommit=False, autoflush=False, expire_on_commit=False
)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    app.dependency_overrides[get_db] = override_get_db
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("ALLOW_MOCK_LOGIN", raising=False)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


async def login(client, email):
    resp = await client.get("/auth/google/callback", params={"mock_email": email})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_mock_login_is_disabled_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/auth/google/callback", params={"mock_email": "victim@example.com"})
        assert resp.status_code == 403


@pytest.mark.anyio
async def test_mock_login_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("ALLOW_MOCK_LOGIN", "false")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/auth/google/callback", params={"mock_email": "victim@example.com"})
        assert resp.status_code == 403


@pytest.mark.anyio
async def test_register_cannot_take_over_google_account():
    """A Google-created account must not gain a password through /auth/register."""
    async with TestingSessionLocal() as db:
        db.add(models.User(name="Real Owner", email="owner@example.com", hashed_password=None))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/register", json={
            "name": "Attacker", "email": "owner@example.com", "password": "attacker-password",
        })
        assert resp.status_code == 400
        assert "Google" in resp.json()["detail"]

        login_resp = await client.post("/auth/login", json={
            "email": "owner@example.com", "password": "attacker-password",
        })
        assert login_resp.status_code in (400, 401)


@pytest.mark.anyio
async def test_audits_require_authentication():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/audits")).status_code == 401
        assert (await client.get(f"/audits/{uuid.uuid4()}")).status_code == 401


@pytest.mark.anyio
async def test_audits_of_other_users_are_hidden():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        alice = await login(client, "alice-audit@example.com")
        bob = await login(client, "bob-audit@example.com")
        proj = await client.post("/projects", json={"name": "Alice Project"}, headers=alice)
        project_id = uuid.UUID(proj.json()["id"])

    async with TestingSessionLocal() as db:
        pr = models.PullRequest(repository="alice/repo", pr_number=1, project_id=project_id)
        db.add(pr)
        await db.commit()
        audit = models.AuditRun(pull_request_id=pr.id, commit_sha="abc", status="COMPLETED", idempotency_key="alice-1")
        db.add(audit)
        await db.commit()
        audit_id = str(audit.id)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert len((await client.get("/audits", headers=alice)).json()) == 1
        assert (await client.get("/audits", headers=bob)).json() == []
        assert (await client.get(f"/audits/{audit_id}", headers=bob)).status_code == 404
        assert (await client.get(f"/audits/{audit_id}", headers=alice)).status_code == 200


# ---------------------------------------------------------------------------
# Webhook signatures
# ---------------------------------------------------------------------------

WEBHOOK_PAYLOAD = {
    "repository": "owner/repo",
    "pr_number": 9,
    "commit_sha": "sha-signed-1",
    "branch_name": "feature",
}


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.mark.anyio
async def test_webhook_rejects_unsigned_requests_when_secret_set(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/webhook", json=WEBHOOK_PAYLOAD)
        assert resp.status_code == 401


@pytest.mark.anyio
async def test_webhook_rejects_wrong_signature(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    body = json.dumps(WEBHOOK_PAYLOAD).encode("utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook", content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign("wrong", body)},
        )
        assert resp.status_code == 401


@pytest.mark.anyio
async def test_webhook_accepts_valid_signature(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    body = json.dumps(WEBHOOK_PAYLOAD).encode("utf-8")
    transport = ASGITransport(app=app)
    with patch("main.execute_audit_pipeline", None):  # no Celery broker in unit tests
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/webhook", content=body,
                headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign("s3cret", body)},
            )
            assert resp.status_code == 202


@pytest.mark.anyio
async def test_webhook_requires_secret_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/webhook", json=WEBHOOK_PAYLOAD)
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Rollback executor
# ---------------------------------------------------------------------------

def _deployment(commit: str, status: str = "ACTIVE") -> models.Deployment:
    return models.Deployment(
        id=uuid.uuid4(), project_id=uuid.uuid4(), commit_sha=commit, image_name="ghcr.io/o/svc",
        image_tag=commit, environment="production", status=status,
    )


@pytest.mark.anyio
async def test_default_executor_without_command_refuses_to_switch(monkeypatch):
    monkeypatch.delenv("ROLLBACK_COMMAND", raising=False)
    executor = DefaultRollbackExecutor()
    with pytest.raises(RollbackExecutorNotConfigured):
        await executor.execute(_deployment("new"), _deployment("old"))


@pytest.mark.anyio
async def test_default_executor_runs_configured_command_with_placeholders(monkeypatch):
    monkeypatch.setenv("ROLLBACK_SERVICE_READY_WAIT", "0")
    monkeypatch.setenv(
        "ROLLBACK_COMMAND",
        'python -c "import sys; sys.exit(0 if sys.argv[1] == \'old-sha\' else 3)" {commit_sha}',
    )
    executor = DefaultRollbackExecutor()
    assert await executor.execute(_deployment("new"), _deployment("old-sha")) is True


@pytest.mark.anyio
async def test_default_executor_reports_command_failure(monkeypatch):
    monkeypatch.setenv("ROLLBACK_SERVICE_READY_WAIT", "0")
    monkeypatch.setenv("ROLLBACK_COMMAND", 'python -c "import sys; sys.exit(7)"')
    with pytest.raises(RuntimeError, match="exited with code 7"):
        await DefaultRollbackExecutor().execute(_deployment("new"), _deployment("old"))


@pytest.mark.anyio
async def test_rollback_without_executor_is_recorded_failed_not_success(monkeypatch):
    monkeypatch.delenv("ROLLBACK_COMMAND", raising=False)
    project_id = uuid.uuid4()
    async with TestingSessionLocal() as db:
        user = models.User(name="u", email="u-rb@example.com")
        db.add(user)
        await db.commit()
        db.add(models.Project(id=project_id, user_id=user.id, name="rb"))
        await db.commit()
        old = models.Deployment(project_id=project_id, commit_sha="old-good", image_name="img", image_tag="old-good",
                                environment="production", status="ACTIVE")
        db.add(old)
        await db.commit()
        new = models.Deployment(project_id=project_id, commit_sha="bad-new", image_name="img", image_tag="bad-new",
                                environment="production", status="FAILED", previous_deployment_id=old.id)
        db.add(new)
        await db.commit()
        new_id = new.id

    agent = RollbackAgent(client=MagicMock(), executor=DefaultRollbackExecutor())
    async with TestingSessionLocal() as db:
        deployment = await db.get(models.Deployment, new_id)
        result = await agent.evaluate_and_execute(
            deployment=deployment, reason="Error rate breached", trigger_source="MANUAL", db=db
        )
    assert result.status == "FAILED"
    assert result.success is False
    assert "ROLLBACK_COMMAND is not set" in result.rollback_record.error_message


@pytest.mark.anyio
async def test_stale_rollback_lock_does_not_block_new_rollbacks(monkeypatch):
    monkeypatch.setenv("ROLLBACK_LOCK_TIMEOUT_SECONDS", "60")
    project_id = uuid.uuid4()
    async with TestingSessionLocal() as db:
        user = models.User(name="u", email="stale@example.com")
        db.add(user)
        await db.commit()
        proj = models.Project(id=project_id, user_id=user.id, name="stale")
        db.add(proj)
        await db.commit()
        dep = models.Deployment(project_id=project_id, commit_sha="c1", image_name="i", image_tag="c1",
                                environment="production", status="ACTIVE")
        db.add(dep)
        await db.commit()
        stale = models.RollbackRecord(
            deployment_id=dep.id, reason="crashed run", trigger_source="MANUAL", status="IN_PROGRESS",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db.add(stale)
        await db.commit()
        stale_id = stale.id

    agent = RollbackAgent(client=MagicMock(), executor=MagicMock())
    async with TestingSessionLocal() as db:
        active = await agent._find_active_rollback(project_id, db, expire_stale=True)
        assert active is None
        await db.commit()
    async with TestingSessionLocal() as db:
        record = await db.get(models.RollbackRecord, stale_id)
        assert record.status == "FAILED"
        assert "Stale rollback lock" in record.error_message


@pytest.mark.anyio
async def test_fresh_rollback_lock_still_blocks(monkeypatch):
    monkeypatch.setenv("ROLLBACK_LOCK_TIMEOUT_SECONDS", "900")
    project_id = uuid.uuid4()
    async with TestingSessionLocal() as db:
        user = models.User(name="u", email="fresh@example.com")
        db.add(user)
        await db.commit()
        db.add(models.Project(id=project_id, user_id=user.id, name="fresh"))
        await db.commit()
        dep = models.Deployment(project_id=project_id, commit_sha="c2", image_name="i", image_tag="c2",
                                environment="production", status="ACTIVE")
        db.add(dep)
        await db.commit()
        db.add(models.RollbackRecord(deployment_id=dep.id, reason="live run", trigger_source="MANUAL",
                                     status="IN_PROGRESS"))
        await db.commit()

    agent = RollbackAgent(client=MagicMock(), executor=MagicMock())
    async with TestingSessionLocal() as db:
        assert await agent._find_active_rollback(project_id, db) is not None


# ---------------------------------------------------------------------------
# Deploy gate: fail closed and logged override
# ---------------------------------------------------------------------------

def test_missing_verdict_blocks_deployment():
    ok, _ = evaluate_trust_gate(None)
    assert ok is False


def _run_pipeline(**overrides):
    client = MagicMock()
    client.post.return_value = MagicMock(status_code=500, text="offline")
    client.patch.return_value = MagicMock(status_code=500, text="offline")
    kwargs = dict(
        project_id="00000000-0000-0000-0000-000000000001",
        commit_sha="abc123",
        image_name="img",
        image_tag="abc123",
        client=client,
    )
    kwargs.update(overrides)
    return run_deployment_pipeline(**kwargs)


def test_block_verdict_stops_deployment_without_override():
    exit_code, result = _run_pipeline(trust_recommendation="BLOCK")
    assert exit_code == 1
    assert result["status"] == "BLOCKED"


def test_override_without_approver_or_short_reason_is_rejected():
    exit_code, result = _run_pipeline(trust_recommendation="BLOCK", override_reason="short", override_by="")
    assert exit_code == 1
    assert "Override rejected" in result["reason"]


def test_override_with_approver_and_reason_is_recorded(monkeypatch):
    import scripts.deploy as deploy_module
    monkeypatch.setattr(
        deploy_module, "verify_target_health",
        lambda **kwargs: (True, {"commit_sha": "abc123", "version": "1.0.0"}, "Health and version verification passed."),
    )
    exit_code, result = _run_pipeline(
        trust_recommendation="BLOCK",
        override_reason="Hotfix for an outage, scanner false positive confirmed by the owner",
        override_by="maintainer-jane",
    )
    assert exit_code == 0
    assert result["status"] == "ACTIVE"
    assert result["gate_override"]["approved_by"] == "maintainer-jane"
    assert result["gate_override"]["trust_recommendation"] == "BLOCK"
