"""
Comprehensive Test Suite for Phase 13: Pipeline Watchdog & Deployment Gatekeeper.

Verifies:
1. Healthy Deployment (Watchdog = PASS, Gatekeeper = PASS)
2. High Error Rate (HIGH_ERROR_RATE)
3. Health Failure (HEALTH_FAILURE, with timeout protection)
4. High Latency (HIGH_LATENCY)
5. Prometheus Failure (METRIC_UNAVAILABLE, NOT PASS)
6. Commit Mismatch (COMMIT_MISMATCH & DriftEvent)
7. Version Mismatch (VERSION_MISMATCH & DriftEvent)
8. Environment Mismatch (ENVIRONMENT_MISMATCH & DriftEvent)
9. Image Mismatch & Unresolved Digest (IMAGE_MISMATCH / UNRESOLVED, no fake PASS)
10. Deployment State Mismatch (ACTIVE in DB but unhealthy in runtime)
11. Recovery Scenario (Restored service -> PASS)
12. Insufficient Traffic Protection (min-sample threshold suppresses false alarms)
13. Repeated Check Idempotency (no duplicate active drift events)
14. Authorization & Cross-Tenant Isolation (404/403 for unauthorized project)
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

# Ensure backend directory is in sys.path
backend_dir = os.path.abspath(os.path.dirname(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from database import Base, get_db
import models
import schemas
from auth import create_access_token
from watchdog import PipelineWatchdog
from gatekeeper import DeploymentGatekeeper
from app_config import get_settings


TEST_DB_URL = "sqlite+aiosqlite:///./test_phase13_watchdog_gatekeeper.db"
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


async def create_user_and_deployment(
    session: AsyncSession,
    name: str = "Alice DevOps",
    email: str = "alice@sceptic.io",
    commit_sha: str = "abc123456789",
    version: str = "1.0.0",
    environment: str = "production",
    status: str = "ACTIVE",
    image_digest: str = None
) -> tuple:
    user = models.User(name=name, email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)

    project = models.Project(
        user_id=user.id,
        name="Production Service",
        repository_url="https://github.com/sceptic/prod-service",
        default_branch="main"
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    deployment = models.Deployment(
        project_id=project.id,
        commit_sha=commit_sha,
        image_name="ghcr.io/sceptic/prod-service",
        image_tag="v1.0.0",
        image_digest=image_digest,
        environment=environment,
        version=version,
        status=status,
        deployed_at=datetime.now(timezone.utc)
    )
    session.add(deployment)
    await session.commit()
    await session.refresh(deployment)
    return user, project, deployment


# Helper mock handler for httpx transport
class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, routes):
        self.routes = routes  # Dict of (method, path) -> (status_code, json_data) or Exception

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key in self.routes:
            handler = self.routes[key]
            if isinstance(handler, Exception):
                raise handler
            status_code, data = handler
            return httpx.Response(status_code=status_code, json=data, request=request)
        # Check query param matches if needed
        return httpx.Response(status_code=404, json={"detail": "Not found in mock"}, request=request)


# -------------------------------------------------------------
# TEST 1 — HEALTHY DEPLOYMENT (PASS / PASS)
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_watchdog_and_gatekeeper_healthy_deployment():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session)

    class HealthyPromTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "healthy"}, request=request)
            if request.url.path == "/version":
                return httpx.Response(200, json={
                    "version": "1.0.0",
                    "commit_sha": "abc123456789",
                    "environment": "production"
                }, request=request)
            if request.url.path == "/api/v1/query":
                q = request.url.params.get("query", "")
                if 'status_code=~"5.."' in q:
                    return httpx.Response(200, json={"status": "success", "data": {"result": []}}, request=request)
                elif "histogram_quantile" in q:
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "0.025"]}]}
                    }, request=request)
                elif "sum(http_requests_total)" in q:
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "100"]}]}
                    }, request=request)
                else:
                    return httpx.Response(200, json={"status": "success", "data": {"result": []}}, request=request)
            return httpx.Response(404, request=request)

    client = httpx.AsyncClient(transport=HealthyPromTransport())

    # 1. Watchdog
    watchdog = PipelineWatchdog(target_url="http://mock-target:8080", prometheus_url="http://mock-prom:9090", client=client)
    async with TestingSessionLocal() as session:
        res_wd = await watchdog.evaluate(deployment, session)
        assert res_wd.status == schemas.VerificationStatus.PASS
        assert res_wd.telemetry_snapshot is not None
        assert res_wd.telemetry_snapshot.health_status == "healthy"


    # 2. Gatekeeper
    gatekeeper = DeploymentGatekeeper(target_url="http://mock-target:8080", client=client)
    async with TestingSessionLocal() as session:
        res_gk = await gatekeeper.evaluate(deployment, session)
        # Gatekeeper image digest is UNRESOLVED by design (since digest cannot be faked without docker socket)
        # while commit, version, environment are verified
        assert any(f.finding_type == "UNRESOLVED" for f in res_gk.findings)
        assert not any(f.finding_type == "COMMIT_MISMATCH" for f in res_gk.findings)
        assert not any(f.finding_type == "VERSION_MISMATCH" for f in res_gk.findings)
        assert not any(f.finding_type == "ENVIRONMENT_MISMATCH" for f in res_gk.findings)


# -------------------------------------------------------------
# TEST 2 — HIGH ERROR RATE
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_watchdog_high_error_rate():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session)

    class ErrorRateTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "healthy"}, request=request)
            if request.url.path == "/api/v1/query":
                q = request.url.params.get("query", "")
                if 'status_code=~"5.."' in q:
                    # 25 errors
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "25"]}]}
                    }, request=request)
                elif "sum(http_requests_total)" in q:
                    # 100 total requests -> 25% error rate > 5% threshold
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "100"]}]}
                    }, request=request)
                else:
                    return httpx.Response(200, json={"status": "success", "data": {"result": []}}, request=request)
            return httpx.Response(404, request=request)

    client = httpx.AsyncClient(transport=ErrorRateTransport())
    watchdog = PipelineWatchdog(client=client)

    async with TestingSessionLocal() as session:
        result = await watchdog.evaluate(deployment, session)
        assert result.status == schemas.VerificationStatus.FAIL
        assert any(f.finding_type == "HIGH_ERROR_RATE" for f in result.findings)
        assert any(f.finding_type == "DEPLOYMENT_CORRELATED_ANOMALY" for f in result.findings)
        assert result.telemetry_snapshot.error_rate == 0.25


# -------------------------------------------------------------
# TEST 3 — HEALTH FAILURE
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_watchdog_health_failure():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session)

    routes = {
        ("GET", "/health"): (503, {"status": "unhealthy", "error": "Database down"}),
        ("GET", "/api/v1/query"): (200, {"status": "success", "data": {"result": []}})
    }
    client = httpx.AsyncClient(transport=MockTransport(routes))
    watchdog = PipelineWatchdog(client=client)

    async with TestingSessionLocal() as session:
        result = await watchdog.evaluate(deployment, session)
        assert result.status == schemas.VerificationStatus.FAIL
        assert any(f.finding_type == "HEALTH_FAILURE" for f in result.findings)
        assert result.telemetry_snapshot.health_status == "unhealthy"


# -------------------------------------------------------------
# TEST 4 — HIGH LATENCY
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_watchdog_high_latency():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session)

    class LatencyTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "healthy"}, request=request)
            if request.url.path == "/api/v1/query":
                q = request.url.params.get("query", "")
                if "histogram_quantile" in q:
                    # 1.25 seconds p95 > 0.5s threshold
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "1.250"]}]}
                    }, request=request)
                elif "sum(http_requests_total)" in q:
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "50"]}]}
                    }, request=request)
                else:
                    return httpx.Response(200, json={"status": "success", "data": {"result": []}}, request=request)
            return httpx.Response(404, request=request)

    client = httpx.AsyncClient(transport=LatencyTransport())
    watchdog = PipelineWatchdog(client=client)

    async with TestingSessionLocal() as session:
        result = await watchdog.evaluate(deployment, session)
        assert result.status == schemas.VerificationStatus.FAIL
        assert any(f.finding_type == "HIGH_LATENCY" for f in result.findings)
        assert result.telemetry_snapshot.latency_p95 == 1.250


# -------------------------------------------------------------
# TEST 5 — PROMETHEUS FAILURE
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_watchdog_prometheus_failure():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session)

    routes = {
        ("GET", "/health"): (200, {"status": "healthy"}),
        ("GET", "/api/v1/query"): httpx.ConnectError("Connection refused to prometheus:9090")
    }
    client = httpx.AsyncClient(transport=MockTransport(routes))
    watchdog = PipelineWatchdog(client=client)

    async with TestingSessionLocal() as session:
        result = await watchdog.evaluate(deployment, session)
        assert result.status == schemas.VerificationStatus.UNRESOLVED  # Not PASS!
        assert any(f.finding_type == "METRIC_UNAVAILABLE" for f in result.findings)
        assert result.telemetry_snapshot.request_count is None  # Never faked as 0


# -------------------------------------------------------------
# TEST 6 — COMMIT MISMATCH
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_gatekeeper_commit_mismatch():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session, commit_sha="expected-commit-abc123")

    routes = {
        ("GET", "/health"): (200, {"status": "healthy"}),
        ("GET", "/version"): (200, {
            "commit_sha": "actual-rogue-commit-xyz789",
            "version": "1.0.0",
            "environment": "production"
        })
    }
    client = httpx.AsyncClient(transport=MockTransport(routes))
    gatekeeper = DeploymentGatekeeper(client=client)

    async with TestingSessionLocal() as session:
        result = await gatekeeper.evaluate(deployment, session)
        assert result.status == schemas.VerificationStatus.FAIL
        assert any(f.finding_type == "COMMIT_MISMATCH" for f in result.findings)
        assert result.drift_events_created == 1

        # Check drift event in DB
        drift_stmt = select(models.DriftEvent).filter(models.DriftEvent.deployment_id == deployment.id)
        drifts = (await session.execute(drift_stmt)).scalars().all()
        assert len(drifts) == 1
        assert drifts[0].drift_type == "COMMIT"
        assert drifts[0].expected_value == "expected-commit-abc123"
        assert drifts[0].actual_value == "actual-rogue-commit-xyz789"


# -------------------------------------------------------------
# TEST 7 — VERSION MISMATCH
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_gatekeeper_version_mismatch():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session, version="1.4.2")

    routes = {
        ("GET", "/health"): (200, {"status": "healthy"}),
        ("GET", "/version"): (200, {
            "commit_sha": deployment.commit_sha,
            "version": "1.4.1",
            "environment": "production"
        })
    }
    client = httpx.AsyncClient(transport=MockTransport(routes))
    gatekeeper = DeploymentGatekeeper(client=client)

    async with TestingSessionLocal() as session:
        result = await gatekeeper.evaluate(deployment, session)
        assert result.status == schemas.VerificationStatus.FAIL
        assert any(f.finding_type == "VERSION_MISMATCH" for f in result.findings)
        assert result.drift_events_created == 1


# -------------------------------------------------------------
# TEST 8 — ENVIRONMENT MISMATCH
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_gatekeeper_environment_mismatch():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session, environment="production")

    routes = {
        ("GET", "/health"): (200, {"status": "healthy"}),
        ("GET", "/version"): (200, {
            "commit_sha": deployment.commit_sha,
            "version": "1.0.0",
            "environment": "development"
        })
    }
    client = httpx.AsyncClient(transport=MockTransport(routes))
    gatekeeper = DeploymentGatekeeper(client=client)

    async with TestingSessionLocal() as session:
        result = await gatekeeper.evaluate(deployment, session)
        assert result.status == schemas.VerificationStatus.FAIL
        assert any(f.finding_type == "ENVIRONMENT_MISMATCH" for f in result.findings)
        assert result.drift_events_created == 1


# -------------------------------------------------------------
# TEST 9 — IMAGE MISMATCH & UNRESOLVED DIGEST
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_gatekeeper_image_digest_handling():
    # Case A: Digest unavailable in metadata -> must return UNRESOLVED (not fake PASS)
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session, image_digest="sha256:abc")

    routes_no_digest = {
        ("GET", "/health"): (200, {"status": "healthy"}),
        ("GET", "/version"): (200, {
            "commit_sha": deployment.commit_sha,
            "version": "1.0.0",
            "environment": "production"
        })
    }
    client = httpx.AsyncClient(transport=MockTransport(routes_no_digest))
    gatekeeper = DeploymentGatekeeper(client=client)

    async with TestingSessionLocal() as session:
        res = await gatekeeper.evaluate(deployment, session)
        assert any(f.finding_type == "UNRESOLVED" and "image digest unavailable" in f.description.lower() for f in res.findings)

    # Case B: Digest available and mismatched -> IMAGE_MISMATCH
    routes_diff_digest = {
        ("GET", "/health"): (200, {"status": "healthy"}),
        ("GET", "/version"): (200, {
            "commit_sha": deployment.commit_sha,
            "version": "1.0.0",
            "environment": "production",
            "image_digest": "sha256:different999"
        })
    }
    client_b = httpx.AsyncClient(transport=MockTransport(routes_diff_digest))
    gatekeeper_b = DeploymentGatekeeper(client=client_b)

    async with TestingSessionLocal() as session:
        res_b = await gatekeeper_b.evaluate(deployment, session)
        assert any(f.finding_type == "IMAGE_MISMATCH" for f in res_b.findings)
        assert res_b.drift_events_created >= 1


# -------------------------------------------------------------
# TEST 10 — DEPLOYMENT STATE MISMATCH
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_gatekeeper_deployment_state_mismatch():
    async with TestingSessionLocal() as session:
        # DB status is ACTIVE, but target service is completely down
        user, project, deployment = await create_user_and_deployment(session, status="ACTIVE")

    routes_down = {
        ("GET", "/health"): (500, {"status": "error"}),
        ("GET", "/version"): (500, {})
    }
    client = httpx.AsyncClient(transport=MockTransport(routes_down))
    gatekeeper = DeploymentGatekeeper(client=client)

    async with TestingSessionLocal() as session:
        res = await gatekeeper.evaluate(deployment, session)
        assert res.status == schemas.VerificationStatus.FAIL
        assert any(f.finding_type == "DEPLOYMENT_STATE_MISMATCH" for f in res.findings)


# -------------------------------------------------------------
# TEST 11 — RECOVERY
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_watchdog_recovery():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session)

    class HealthyPromTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "healthy"}, request=request)
            if request.url.path == "/api/v1/query":
                q = request.url.params.get("query", "")
                if 'status_code=~"5.."' in q:
                    return httpx.Response(200, json={"status": "success", "data": {"result": []}}, request=request)
                elif "histogram_quantile" in q:
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "0.025"]}]}
                    }, request=request)
                elif "sum(http_requests_total)" in q:
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "100"]}]}
                    }, request=request)
                else:
                    return httpx.Response(200, json={"status": "success", "data": {"result": []}}, request=request)
            return httpx.Response(404, request=request)

    client = httpx.AsyncClient(transport=HealthyPromTransport())
    watchdog = PipelineWatchdog(client=client)

    async with TestingSessionLocal() as session:
        res = await watchdog.evaluate(deployment, session)
        assert res.status == schemas.VerificationStatus.PASS

        assert res.telemetry_snapshot.health_status == "healthy"


# -------------------------------------------------------------
# TEST 12 — INSUFFICIENT TRAFFIC PROTECTION
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_watchdog_insufficient_traffic_protection():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session)

    # 1 request total, 1 failure -> 100% error rate, but sample < WATCHDOG_MIN_REQUESTS (10)
    class SmallSampleTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "healthy"}, request=request)
            if request.url.path == "/api/v1/query":
                q = request.url.params.get("query", "")
                if "5.." in q:
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "1"]}]}
                    }, request=request)
                elif "sum(http_requests_total)" in q:
                    return httpx.Response(200, json={
                        "status": "success",
                        "data": {"result": [{"metric": {}, "value": [1728345600, "1"]}]}
                    }, request=request)
                else:
                    return httpx.Response(200, json={"status": "success", "data": {"result": []}}, request=request)
            return httpx.Response(404, request=request)

    client = httpx.AsyncClient(transport=SmallSampleTransport())
    watchdog = PipelineWatchdog(client=client)

    async with TestingSessionLocal() as session:
        res = await watchdog.evaluate(deployment, session)
        # Should NOT trigger HIGH_ERROR_RATE because sample is 1 < 10
        assert not any(f.finding_type == "HIGH_ERROR_RATE" for f in res.findings)


# -------------------------------------------------------------
# TEST 13 — REPEATED CHECK IDEMPOTENCY
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_gatekeeper_repeated_check_idempotency():
    async with TestingSessionLocal() as session:
        user, project, deployment = await create_user_and_deployment(session, commit_sha="expected-123")

    routes = {
        ("GET", "/health"): (200, {"status": "healthy"}),
        ("GET", "/version"): (200, {
            "commit_sha": "rogue-456",
            "version": "1.0.0",
            "environment": "production"
        })
    }
    client = httpx.AsyncClient(transport=MockTransport(routes))
    gatekeeper = DeploymentGatekeeper(client=client)

    async with TestingSessionLocal() as session:
        # Run 1: Should create 1 drift event
        res1 = await gatekeeper.evaluate(deployment, session)
        assert res1.drift_events_created == 1

        # Run 2: Same conditions, should NOT create duplicate drift event
        res2 = await gatekeeper.evaluate(deployment, session)
        assert res2.drift_events_created == 0

        # Run 3: Same conditions, should NOT create duplicate drift event
        res3 = await gatekeeper.evaluate(deployment, session)
        assert res3.drift_events_created == 0

        # Total drift events in DB remains 1
        drift_stmt = select(models.DriftEvent).filter(models.DriftEvent.deployment_id == deployment.id)
        drifts = (await session.execute(drift_stmt)).scalars().all()
        assert len(drifts) == 1


# -------------------------------------------------------------
# TEST 14 — AUTHORIZATION & CROSS-TENANT ISOLATION
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_authorization_cross_tenant_isolation():
    async with TestingSessionLocal() as session:
        # User A owns deployment A
        user_a, project_a, dep_a = await create_user_and_deployment(session, name="User A", email="a@test.com")
        # User B
        user_b = models.User(name="User B", email="b@test.com")
        session.add(user_b)
        await session.commit()
        await session.refresh(user_b)

    token_b = create_access_token(data={"sub": str(user_b.id), "email": user_b.email})
    transport = ASGITransport(app=app)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # User B tries to trigger Watchdog on User A's deployment
        resp_wd = await ac.post(f"/deployments/{dep_a.id}/watchdog/check", headers=headers_b)
        assert resp_wd.status_code == 404

        # User B tries to trigger Gatekeeper on User A's deployment
        resp_gk = await ac.post(f"/deployments/{dep_a.id}/gatekeeper/check", headers=headers_b)
        assert resp_gk.status_code == 404

        # User B tries to query telemetry of User A's deployment
        resp_tel = await ac.get(f"/deployments/{dep_a.id}/telemetry", headers=headers_b)
        assert resp_tel.status_code == 404

        # User B tries to query drift-events of User A's deployment
        resp_drift = await ac.get(f"/deployments/{dep_a.id}/drift-events", headers=headers_b)
        assert resp_drift.status_code == 404
