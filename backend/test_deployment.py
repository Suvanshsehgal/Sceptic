"""
Tests for Phase 10: Deployment State & Database.
Verifies models, relationships, cascading/null behaviors, API endpoints,
strict multi-tenant project ownership authorization, and validation rules.
"""
import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from main import app
from database import Base, get_db
import models
import schemas
from auth import create_access_token

TEST_DB_URL = "sqlite+aiosqlite:///./test_deployment_phase10.db"
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


async def create_user_and_project(session: AsyncSession, name: str, email: str, proj_name: str):
    user = models.User(name=name, email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)

    project = models.Project(
        user_id=user.id,
        name=proj_name,
        repository_url=f"https://github.com/org/{proj_name}",
        default_branch="main"
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    token = create_access_token(data={"sub": str(user.id), "email": user.email, "name": user.name})
    return user, project, token


# ========================================================
# 1. DATABASE MODEL & RELATIONSHIP TESTS
# ========================================================

@pytest.mark.anyio
async def test_deployment_model_and_relationships():
    async with TestingSessionLocal() as session:
        user, project, _ = await create_user_and_project(session, "Dev User", "dev@sceptic.io", "alpha-service")

        # 1. Create first deployment
        dep1 = models.Deployment(
            project_id=project.id,
            commit_sha="a1b2c3d4",
            image_name="sceptic/alpha-service",
            image_tag="v1.0.0",
            image_digest="sha256:1111111111111111",
            environment="production",
            version="1.0.0",
            status="ACTIVE",
            deployed_at=datetime.now(timezone.utc)
        )
        session.add(dep1)
        await session.commit()
        await session.refresh(dep1)
        assert dep1.id is not None
        assert dep1.status == "ACTIVE"

        # 2. Create second deployment linked to previous_deployment_id
        dep2 = models.Deployment(
            project_id=project.id,
            commit_sha="e5f6a7b8",
            image_name="sceptic/alpha-service",
            image_tag="v1.1.0",
            environment="production",
            version="1.1.0",
            status="ACTIVE",
            previous_deployment_id=dep1.id,
            deployed_at=datetime.now(timezone.utc)
        )
        session.add(dep2)
        await session.commit()
        await session.refresh(dep2)
        assert dep2.previous_deployment_id == dep1.id

        # 3. Add TelemetrySnapshot to dep2
        snap = models.TelemetrySnapshot(
            deployment_id=dep2.id,
            health_status="healthy",
            request_count=1500,
            error_count=3,
            error_rate=0.002,
            latency_avg=45.2,
            latency_p95=98.5
        )
        session.add(snap)

        # 4. Add DriftEvent to dep2
        drift = models.DriftEvent(
            deployment_id=dep2.id,
            drift_type="IMAGE_DIGEST",
            expected_value="sha256:expected",
            actual_value="sha256:actual",
            severity="HIGH",
            description="Container image digest mismatched active deployment spec"
        )
        session.add(drift)

        # 5. Add RollbackRecord targeting dep1
        rollback = models.RollbackRecord(
            deployment_id=dep2.id,
            target_deployment_id=dep1.id,
            reason="High error spike detected in v1.1.0",
            trigger_source="WATCHDOG",
            status="COMPLETED"
        )
        session.add(rollback)
        await session.commit()

        # Query and verify relationships
        res = await session.execute(
            select(models.Deployment).filter(models.Deployment.id == dep2.id)
        )
        loaded = res.scalars().first()
        assert loaded is not None

        # Project relationship
        assert loaded.project_id == project.id


@pytest.mark.anyio
async def test_safe_foreign_key_previous_deployment():
    """Verify that deleting a previous deployment sets previous_deployment_id to NULL without cascading."""
    async with TestingSessionLocal() as session:
        user, project, _ = await create_user_and_project(session, "Dev User", "dev2@sceptic.io", "beta-service")

        dep1 = models.Deployment(
            project_id=project.id,
            commit_sha="commit-1",
            image_name="service-b",
            image_tag="1.0",
            status="ACTIVE"
        )
        session.add(dep1)
        await session.commit()
        await session.refresh(dep1)

        dep2 = models.Deployment(
            project_id=project.id,
            commit_sha="commit-2",
            image_name="service-b",
            image_tag="2.0",
            status="ACTIVE",
            previous_deployment_id=dep1.id
        )
        session.add(dep2)
        await session.commit()
        await session.refresh(dep2)

        # Delete dep1
        await session.delete(dep1)
        await session.commit()

        # dep2 must still exist, with previous_deployment_id set to NULL
        res = await session.execute(
            select(models.Deployment).filter(models.Deployment.id == dep2.id)
        )
        dep2_reloaded = res.scalars().first()
        assert dep2_reloaded is not None
        assert dep2_reloaded.previous_deployment_id is None


# ========================================================
# 2. API ENDPOINTS & LIFECYCLE TESTS
# ========================================================

@pytest.mark.anyio
async def test_deployment_crud_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with TestingSessionLocal() as session:
            user, project, token = await create_user_and_project(session, "Alice", "alice@sceptic.io", "service-x")

        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Deployment
        create_payload = {
            "commit_sha": "abc123def456",
            "image_name": "registry.sceptic.local/service-x",
            "image_tag": "v2.0.0",
            "image_digest": "sha256:abcde12345",
            "environment": "production",
            "version": "2.0.0",
            "status": "DEPLOYING"
        }
        res = await client.post(f"/projects/{project.id}/deployments", json=create_payload, headers=headers)
        assert res.status_code == 201
        dep_data = res.json()
        dep_id = dep_data["id"]
        assert dep_data["commit_sha"] == "abc123def456"
        assert dep_data["status"] == "DEPLOYING"
        assert dep_data["project_id"] == str(project.id)

        # 2. List Deployments for project
        res_list = await client.get(f"/projects/{project.id}/deployments", headers=headers)
        assert res_list.status_code == 200
        items = res_list.json()
        assert len(items) == 1
        assert items[0]["id"] == dep_id

        # 3. Get Deployment by ID
        res_get = await client.get(f"/deployments/{dep_id}", headers=headers)
        assert res_get.status_code == 200
        assert res_get.json()["id"] == dep_id

        # 4. Record Telemetry Snapshot
        telemetry_payload = {
            "health_status": "healthy",
            "request_count": 250,
            "error_count": 1,
            "error_rate": 0.004,
            "latency_avg": 35.5,
            "latency_p95": 82.1
        }
        res_telemetry = await client.post(f"/deployments/{dep_id}/telemetry", json=telemetry_payload, headers=headers)
        assert res_telemetry.status_code == 201
        assert res_telemetry.json()["health_status"] == "healthy"
        assert res_telemetry.json()["error_rate"] == 0.004

        # List Telemetry
        res_t_list = await client.get(f"/deployments/{dep_id}/telemetry", headers=headers)
        assert res_t_list.status_code == 200
        assert len(res_t_list.json()) == 1

        # 5. Record Drift Event
        drift_payload = {
            "drift_type": "CONFIGURATION",
            "expected_value": "LOG_LEVEL=INFO",
            "actual_value": "LOG_LEVEL=DEBUG",
            "severity": "LOW",
            "description": "Environment variable LOG_LEVEL drifted in runtime pod"
        }
        res_drift = await client.post(f"/deployments/{dep_id}/drift", json=drift_payload, headers=headers)
        assert res_drift.status_code == 201
        assert res_drift.json()["drift_type"] == "CONFIGURATION"

        # List Drift
        res_d_list = await client.get(f"/deployments/{dep_id}/drift", headers=headers)
        assert res_d_list.status_code == 200
        assert len(res_d_list.json()) == 1

        # 6. Record Rollback
        rollback_payload = {
            "reason": "Test rollback trigger",
            "trigger_source": "MANUAL",
            "status": "PENDING"
        }
        res_rb = await client.post(f"/deployments/{dep_id}/rollbacks", json=rollback_payload, headers=headers)
        assert res_rb.status_code == 201
        assert res_rb.json()["reason"] == "Test rollback trigger"

        # List Rollbacks
        res_rb_list = await client.get(f"/deployments/{dep_id}/rollbacks", headers=headers)
        assert res_rb_list.status_code == 200
        assert len(res_rb_list.json()) == 1


# ========================================================
# 3. MULTI-TENANT AUTHORIZATION TESTS
# ========================================================

@pytest.mark.anyio
async def test_authorization_cross_user_isolation():
    """Verify that User B cannot access, list, or create deployments for User A's project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with TestingSessionLocal() as session:
            # User A and Project A
            user_a, project_a, token_a = await create_user_and_project(session, "Alice", "alice_iso@sceptic.io", "proj-a")
            # User B and Project B
            user_b, project_b, token_b = await create_user_and_project(session, "Bob", "bob_iso@sceptic.io", "proj-b")

            # Create deployment under Project A
            dep_a = models.Deployment(
                project_id=project_a.id,
                commit_sha="sha-alice-1",
                image_name="alice/app",
                image_tag="1.0",
                status="ACTIVE"
            )
            session.add(dep_a)
            await session.commit()
            await session.refresh(dep_a)

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # User A can access Deployment A
        res_a = await client.get(f"/deployments/{dep_a.id}", headers=headers_a)
        assert res_a.status_code == 200

        # User B CANNOT access Deployment A (returns 404)
        res_b_dep = await client.get(f"/deployments/{dep_a.id}", headers=headers_b)
        assert res_b_dep.status_code == 404

        # User B CANNOT list deployments for Project A (returns 404)
        res_b_list = await client.get(f"/projects/{project_a.id}/deployments", headers=headers_b)
        assert res_b_list.status_code == 404

        # User B CANNOT create deployment under Project A (returns 404)
        create_payload = {
            "commit_sha": "malicious-sha",
            "image_name": "bob/impostor",
            "image_tag": "v1.0",
            "status": "PENDING"
        }
        res_b_create = await client.post(f"/projects/{project_a.id}/deployments", json=create_payload, headers=headers_b)
        assert res_b_create.status_code == 404

        # User B CANNOT view or add telemetry for Deployment A (returns 404)
        res_b_telem = await client.get(f"/deployments/{dep_a.id}/telemetry", headers=headers_b)
        assert res_b_telem.status_code == 404

        # User B CANNOT view drift or rollbacks for Deployment A (returns 404)
        res_b_drift = await client.get(f"/deployments/{dep_a.id}/drift", headers=headers_b)
        assert res_b_drift.status_code == 404
        res_b_rb = await client.get(f"/deployments/{dep_a.id}/rollbacks", headers=headers_b)
        assert res_b_rb.status_code == 404


# ========================================================
# 4. VALIDATION & ERROR HANDLING TESTS
# ========================================================

@pytest.mark.anyio
async def test_validation_rejection_rules():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with TestingSessionLocal() as session:
            user, project, token = await create_user_and_project(session, "Charlie", "charlie@sceptic.io", "proj-c")

            dep = models.Deployment(
                project_id=project.id,
                commit_sha="valid-sha",
                image_name="test/app",
                image_tag="1.0",
                status="ACTIVE"
            )
            session.add(dep)
            await session.commit()
            await session.refresh(dep)

        headers = {"Authorization": f"Bearer {token}"}

        # 1. Invalid status rejected
        invalid_status_payload = {
            "commit_sha": "sha-test",
            "image_name": "test/app",
            "image_tag": "1.0",
            "status": "UNRECOGNIZED_STATUS"
        }
        res1 = await client.post(f"/projects/{project.id}/deployments", json=invalid_status_payload, headers=headers)
        assert res1.status_code == 422

        # 2. Negative telemetry count rejected
        neg_count_payload = {
            "health_status": "healthy",
            "request_count": -10
        }
        res2 = await client.post(f"/deployments/{dep.id}/telemetry", json=neg_count_payload, headers=headers)
        assert res2.status_code == 422

        # 3. Negative latency rejected
        neg_latency_payload = {
            "health_status": "healthy",
            "latency_avg": -5.0
        }
        res3 = await client.post(f"/deployments/{dep.id}/telemetry", json=neg_latency_payload, headers=headers)
        assert res3.status_code == 422

        # 4. Out-of-range error rate rejected (> 1.0)
        high_err_payload = {
            "health_status": "healthy",
            "error_rate": 1.5
        }
        res4 = await client.post(f"/deployments/{dep.id}/telemetry", json=high_err_payload, headers=headers)
        assert res4.status_code == 422

        # 5. Invalid UUID format rejected in path
        res5 = await client.get("/deployments/not-a-valid-uuid", headers=headers)
        assert res5.status_code == 422
