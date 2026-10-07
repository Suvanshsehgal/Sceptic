"""
Tests for Authentication, Google OAuth callback, User management, Project ownership, and Feature Analysis.
"""
import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from main import app
from database import Base, get_db
import models
from auth import create_access_token

TEST_DB_URL = "sqlite+aiosqlite:///./test_auth_api.db"
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
async def test_unauthenticated_request_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/auth/me")
        assert resp.status_code == 401
        assert "Authentication token is required" in resp.json()["detail"]


@pytest.mark.anyio
async def test_oauth_login_url_generation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/auth/google/login")
        assert resp.status_code == 200
        data = resp.json()
        assert "auth_url" in data
        assert "state" in data
        assert "accounts.google.com" in data["auth_url"]


@pytest.mark.anyio
async def test_oauth_callback_creates_user_and_issues_jwt():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Hermetic mock callback
        resp = await client.get(
            "/auth/google/callback",
            params={"mock_email": "alice@example.com", "mock_name": "Alice Developer"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["email"] == "alice@example.com"
        assert data["user"]["name"] == "Alice Developer"

        # Verify /auth/me with the issued token
        token = data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        me_resp = await client.get("/auth/me", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["email"] == "alice@example.com"


@pytest.mark.anyio
async def test_project_ownership_and_isolation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create Alice
        resp_a = await client.get("/auth/google/callback", params={"mock_email": "alice@example.com"})
        token_a = resp_a.json()["access_token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # Create Bob
        resp_b = await client.get("/auth/google/callback", params={"mock_email": "bob@example.com"})
        token_b = resp_b.json()["access_token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # Alice creates a project
        proj_resp = await client.post(
            "/projects",
            json={"name": "Alice Project", "repository_url": "https://github.com/alice/project"},
            headers=headers_a
        )
        assert proj_resp.status_code == 201
        proj_id = proj_resp.json()["id"]

        # Alice can list and retrieve her project
        list_a = await client.get("/projects", headers=headers_a)
        assert len(list_a.json()) == 1
        assert list_a.json()[0]["id"] == proj_id

        get_a = await client.get(f"/projects/{proj_id}", headers=headers_a)
        assert get_a.status_code == 200

        # Bob CANNOT see or access Alice's project (Isolation)
        list_b = await client.get("/projects", headers=headers_b)
        assert len(list_b.json()) == 0

        get_b = await client.get(f"/projects/{proj_id}", headers=headers_b)
        assert get_b.status_code == 404


@pytest.mark.anyio
async def test_feature_analysis_creation_and_ownership():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/auth/google/callback", params={"mock_email": "charlie@example.com"})
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create project
        p_resp = await client.post("/projects", json={"name": "AI Verification Core"}, headers=headers)
        proj_id = p_resp.json()["id"]

        # Create feature analysis
        feat_resp = await client.post(
            f"/projects/{proj_id}/feature-analyses",
            json={"feature_description": "Implement multi-tenant audit caching"},
            headers=headers
        )
        assert feat_resp.status_code == 201
        data = feat_resp.json()
        assert data["feasibility_score"] > 0
        assert "implementation_plan" in data

        # List analyses
        list_feat = await client.get(f"/projects/{proj_id}/feature-analyses", headers=headers)
        assert len(list_feat.json()) == 1
        assert list_feat.json()[0]["id"] == data["id"]
