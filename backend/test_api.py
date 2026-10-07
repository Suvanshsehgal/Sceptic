import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from main import app
from database import Base, get_db
import models

# Use test SQLite database file for testing
TEST_DB_URL = "sqlite+aiosqlite:///./test_api_db.db"
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


@pytest.mark.anyio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_health_db_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/db")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
        assert response.json()["database"] == 1


@pytest.mark.anyio
async def test_get_audits_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audits")
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.anyio
async def test_get_audits_with_data():
    async with TestingSessionLocal() as db:
        pr = models.PullRequest(repository="test/repo", pr_number=1, latest_commit_sha="abc1234")
        db.add(pr)
        await db.commit()

        audit = models.AuditRun(
            pull_request_id=pr.id,
            commit_sha="abc1234",
            status="QUEUED",
            idempotency_key="idemp_1"
        )
        db.add(audit)
        await db.commit()

        finding = models.AgentFinding(
            audit_run_id=audit.id,
            agent_name="FACT_CHECKER",
            title="Test Finding",
            description="Desc"
        )
        db.add(finding)
        await db.commit()
        audit_id = str(audit.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audits")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == audit_id
        assert len(data[0]["findings"]) == 1
        assert data[0]["findings"][0]["title"] == "Test Finding"


@pytest.mark.anyio
async def test_get_audit_by_id():
    async with TestingSessionLocal() as db:
        pr = models.PullRequest(repository="org/repo", pr_number=42, latest_commit_sha="def5678")
        db.add(pr)
        await db.commit()

        audit = models.AuditRun(
            pull_request_id=pr.id,
            commit_sha="def5678",
            status="COMPLETED",
            trust_score=92.0,
            idempotency_key="idemp_2"
        )
        db.add(audit)
        await db.commit()
        audit_id = str(audit.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/audits/{audit_id}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == audit_id
        assert body["trust_score"] == 92.0
        assert body["status"] == "COMPLETED"

        # Test not found
        random_uuid = str(uuid.uuid4())
        res_not_found = await client.get(f"/audits/{random_uuid}")
        assert res_not_found.status_code == 404


@pytest.mark.anyio
async def test_auth_register_and_login_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Register new user
        reg_resp = await client.post("/auth/register", json={
            "name": "Alice Developer",
            "email": "alice@example.com",
            "password": "supersecretpassword123"
        })
        assert reg_resp.status_code == 201
        reg_data = reg_resp.json()
        assert "access_token" in reg_data
        assert reg_data["user"]["email"] == "alice@example.com"
        assert reg_data["user"]["name"] == "Alice Developer"

        # 2. Login with correct password
        login_resp = await client.post("/auth/login", json={
            "email": "alice@example.com",
            "password": "supersecretpassword123"
        })
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        # 3. Access /auth/me with Bearer token
        me_resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["email"] == "alice@example.com"


@pytest.mark.anyio
async def test_auth_invalid_password():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/auth/register", json={
            "name": "Bob Tester",
            "email": "bob@example.com",
            "password": "correctpassword123"
        })
        # Try wrong password
        login_resp = await client.post("/auth/login", json={
            "email": "bob@example.com",
            "password": "wrongpassword"
        })
        assert login_resp.status_code == 401

