"""
Phase 2 tests: audit progress stream, live deployment metrics, alert dispatch, workflow change guard.
"""
import os
import uuid
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from main import app
from database import Base, get_db
import models
import alerts
import workflow_guard
from gatekeeper import DeploymentGatekeeper

TEST_DB_URL = "sqlite+aiosqlite:///./test_phase2_features.db"
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
    for name in ("ALERT_SLACK_WEBHOOK_URL", "ALERT_DISCORD_WEBHOOK_URL", "GATEKEEPER_REPO_PATH", "WORKFLOW_APPROVED_COMMITS"):
        monkeypatch.delenv(name, raising=False)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


async def login(client, email):
    resp = await client.get("/auth/google/callback", params={"mock_email": email})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token


async def owned_audit(client, headers, status="COMPLETED", progress=None):
    proj = await client.post("/projects", json={"name": "Stream Project"}, headers=headers)
    project_id = uuid.UUID(proj.json()["id"])
    async with TestingSessionLocal() as db:
        pr = models.PullRequest(repository="o/r", pr_number=3, project_id=project_id)
        db.add(pr)
        await db.commit()
        audit = models.AuditRun(
            pull_request_id=pr.id, commit_sha="abc1234", status=status, trust_score=91.0,
            recommendation="APPROVE", idempotency_key=f"stream-{uuid.uuid4().hex}",
            progress=progress,
        )
        db.add(audit)
        await db.commit()
        return str(audit.id)


# ---------------------------------------------------------------------------
# Audit progress stream (SSE)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_stream_emits_progress_and_done_for_completed_audit():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers, token = await login(client, "stream-owner@example.com")
        progress = {"stage": "RUNNING", "agents": {"Fact-Checker": {"status": "done", "findings": 2}}}
        audit_id = await owned_audit(client, headers, status="COMPLETED", progress=progress)

        async with client.stream("GET", f"/audits/{audit_id}/stream", params={"token": token}) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = (await resp.aread()).decode("utf-8")

    assert "event: progress" in body
    assert "event: done" in body
    assert '"Fact-Checker"' in body
    assert '"trust_score": 91.0' in body


@pytest.mark.anyio
async def test_stream_accepts_bearer_header():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers, _ = await login(client, "stream-header@example.com")
        audit_id = await owned_audit(client, headers, status="FAILED")
        async with client.stream("GET", f"/audits/{audit_id}/stream", headers=headers) as resp:
            assert resp.status_code == 200
            body = (await resp.aread()).decode("utf-8")
    assert "event: done" in body


@pytest.mark.anyio
async def test_stream_requires_authentication():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/audits/{uuid.uuid4()}/stream")
        assert resp.status_code == 401


@pytest.mark.anyio
async def test_stream_hides_other_users_audits():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        owner_headers, _ = await login(client, "stream-a@example.com")
        audit_id = await owned_audit(client, owner_headers)
        _, intruder_token = await login(client, "stream-b@example.com")
        resp = await client.get(f"/audits/{audit_id}/stream", params={"token": intruder_token})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Live deployment metrics
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_live_metrics_reports_current_values_without_storing(monkeypatch):
    from watchdog import PipelineWatchdog

    async def fake_health(self, client):
        return "healthy", None

    async def fake_metrics(self, client):
        return 120, 6, 0.05, 0.02, 0.31, []

    monkeypatch.setattr(PipelineWatchdog, "check_health", fake_health)
    monkeypatch.setattr(PipelineWatchdog, "evaluate_metrics", fake_metrics)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers, _ = await login(client, "live-owner@example.com")
        proj = await client.post("/projects", json={"name": "Live"}, headers=headers)
        project_id = uuid.UUID(proj.json()["id"])
        async with TestingSessionLocal() as db:
            dep = models.Deployment(project_id=project_id, commit_sha="live-sha", image_name="i", image_tag="t",
                                    environment="production", status="ACTIVE")
            db.add(dep)
            await db.commit()
            dep_id = str(dep.id)

        resp = await client.get(f"/deployments/{dep_id}/live", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["health_status"] == "healthy"
        assert body["request_count"] == 120
        assert body["error_rate"] == 0.05
        assert body["latency_p95"] == 0.31

        telemetry = await client.get(f"/deployments/{dep_id}/telemetry", headers=headers)
        assert telemetry.json() == []  # live reads do not persist snapshots


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_alert_without_channel_is_a_no_op():
    result = await alerts.dispatch_alert("Test", {"k": "v"})
    assert result["delivered"] is False


@pytest.mark.anyio
async def test_alert_rejects_non_https_webhook(monkeypatch):
    monkeypatch.setenv("ALERT_SLACK_WEBHOOK_URL", "http://insecure.example.com/hook")
    result = await alerts.dispatch_alert("Test", {"k": "v"})
    assert result["delivered"] is False  # the http URL is ignored, so no channel is left


@pytest.mark.anyio
async def test_alert_posts_to_slack_and_discord(monkeypatch):
    monkeypatch.setenv("ALERT_SLACK_WEBHOOK_URL", "https://hooks.slack.example/T/B/X")
    monkeypatch.setenv("ALERT_DISCORD_WEBHOOK_URL", "https://discord.example/api/webhooks/1/abc")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), request.read().decode("utf-8")))
        return httpx.Response(200)

    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    with patch("alerts.httpx.AsyncClient", side_effect=factory):
        result = await alerts.dispatch_alert("Watchdog breach", {"deployment_id": "d1"})

    assert result["slack"]["delivered"] is True
    assert result["discord"]["delivered"] is True
    urls = [c[0] for c in calls]
    assert "https://hooks.slack.example/T/B/X" in urls
    assert any("discord.example" in u for u in urls)
    assert all("Watchdog breach" in body for _, body in calls)


@pytest.mark.anyio
async def test_alert_failure_never_raises(monkeypatch):
    monkeypatch.setenv("ALERT_SLACK_WEBHOOK_URL", "https://hooks.slack.example/down")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        return original(*args, transport=httpx.MockTransport(handler), **kwargs)

    with patch("alerts.httpx.AsyncClient", side_effect=factory):
        result = await alerts.dispatch_alert("Test", {"k": "v"})
    assert result["slack"]["delivered"] is False


# ---------------------------------------------------------------------------
# Workflow change guard (real git repository)
# ---------------------------------------------------------------------------

def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo_with_workflow_change():
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tempfile.mkdtemp(prefix="sceptic-wf-")
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "test")
        os.makedirs(os.path.join(repo, ".github", "workflows"))
        with open(os.path.join(repo, "app.py"), "w") as f:
            f.write("x = 1\n")
        with open(os.path.join(repo, ".github", "workflows", "ci.yml"), "w") as f:
            f.write("name: ci\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
        base = _git(repo, "rev-parse", "HEAD")
        with open(os.path.join(repo, ".github", "workflows", "ci.yml"), "a") as f:
            f.write("# skip tests\n")
        with open(os.path.join(repo, "app.py"), "a") as f:
            f.write("y = 2\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "change workflow")
        head = _git(repo, "rev-parse", "HEAD")
        yield repo, base, head
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_workflow_change_is_flagged_when_unapproved(repo_with_workflow_change):
    repo, base, head = repo_with_workflow_change
    changed = workflow_guard.unapproved_workflow_changes(repo, base, head, approved=set())
    assert changed == [".github/workflows/ci.yml"]


def test_workflow_change_passes_when_head_is_approved(repo_with_workflow_change):
    repo, base, head = repo_with_workflow_change
    assert workflow_guard.unapproved_workflow_changes(repo, base, head, approved={head[:12]}) == []


def test_non_workflow_changes_are_not_flagged(repo_with_workflow_change):
    repo, base, head = repo_with_workflow_change
    # app.py changed too, but only workflow files are reported.
    changed = workflow_guard.unapproved_workflow_changes(repo, base, head, approved=set())
    assert all(path.startswith(".github/workflows/") for path in changed)


def test_guard_rejects_non_sha_input(repo_with_workflow_change):
    repo, _, head = repo_with_workflow_change
    with pytest.raises(RuntimeError):
        workflow_guard.changed_files(repo, "HEAD; rm -rf /", head)


@pytest.mark.anyio
async def test_gatekeeper_flags_unapproved_workflow_change(repo_with_workflow_change, monkeypatch):
    repo, base, head = repo_with_workflow_change
    monkeypatch.setenv("GATEKEEPER_REPO_PATH", repo)
    project_id = uuid.uuid4()
    async with TestingSessionLocal() as db:
        user = models.User(name="gk", email="gk@example.com")
        db.add(user)
        await db.commit()
        db.add(models.Project(id=project_id, user_id=user.id, name="gk"))
        await db.commit()
        previous = models.Deployment(project_id=project_id, commit_sha=base, image_name="i", image_tag="b",
                                     environment="production", status="ROLLED_BACK")
        db.add(previous)
        await db.commit()
        current = models.Deployment(project_id=project_id, commit_sha=head, image_name="i", image_tag="h",
                                    environment="production", status="ACTIVE",
                                    previous_deployment_id=previous.id)
        db.add(current)
        await db.commit()
        current_id = current.id
        current_commit = current.commit_sha

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "healthy"})
        return httpx.Response(200, json={"commit_sha": current_commit, "version": "1.0.0", "environment": "production"})

    gatekeeper = DeploymentGatekeeper(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    async with TestingSessionLocal() as db:
        deployment = await db.get(models.Deployment, current_id)
        result = await gatekeeper.evaluate(deployment, db)

    flagged = [f for f in result.findings if f.finding_type == "WORKFLOW_CHANGE_UNAPPROVED"]
    assert len(flagged) == 1
    assert flagged[0].actual_value == ".github/workflows/ci.yml"
    assert result.status.value == "FAIL"
    assert result.drift_events_created >= 1
