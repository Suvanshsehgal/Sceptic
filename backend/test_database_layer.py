import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, text

from main import app
from database import Base, get_db
import models
import schemas

# Isolated SQLite async test database
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_async_db.db"
test_async_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestAsyncSessionLocal = async_sessionmaker(
    bind=test_async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

async def override_get_db():
    async with TestAsyncSessionLocal() as session:
        yield session

@pytest_asyncio.fixture(autouse=True)
async def setup_test_database():
    app.dependency_overrides[get_db] = override_get_db
    async with test_async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.anyio
async def test_health_endpoints():
    """Verify GET /health and GET /health/db return healthy status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # General health
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        # DB health check (SELECT 1)
        res_db = await client.get("/health/db")
        assert res_db.status_code == 200
        assert res_db.json()["status"] == "healthy"
        assert res_db.json()["database"] == 1


@pytest.mark.anyio
async def test_pull_request_creation_and_uniqueness():
    """Verify PullRequest creation and (repository, pr_number) uniqueness constraint."""
    async with TestAsyncSessionLocal() as db:
        pr1 = models.PullRequest(
            repository="owner/repo",
            pr_number=10,
            title="Add authentication",
            source_branch="feature-auth",
            author="dev1",
            latest_commit_sha="sha111"
        )
        db.add(pr1)
        await db.commit()
        await db.refresh(pr1)

        assert pr1.id is not None
        assert isinstance(pr1.id, uuid.UUID)
        assert pr1.repository == "owner/repo"

        # Duplicate repository + pr_number should raise IntegrityError
        pr2 = models.PullRequest(
            repository="owner/repo",
            pr_number=10,
            title="Duplicate PR",
            latest_commit_sha="sha222"
        )
        db.add(pr2)
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.anyio
async def test_audit_run_creation_and_idempotency_key():
    """Verify AuditRun association with PullRequest and unique idempotency_key constraint."""
    async with TestAsyncSessionLocal() as db:
        pr = models.PullRequest(repository="org/repo", pr_number=1, latest_commit_sha="c1")
        db.add(pr)
        await db.commit()
        await db.refresh(pr)

        audit1 = models.AuditRun(
            pull_request_id=pr.id,
            commit_sha="c1",
            status="QUEUED",
            idempotency_key="key_unique_1"
        )
        db.add(audit1)
        await db.commit()
        await db.refresh(audit1)

        assert audit1.id is not None
        assert audit1.pull_request_id == pr.id

        # Duplicate idempotency_key
        audit2 = models.AuditRun(
            pull_request_id=pr.id,
            commit_sha="c1",
            status="QUEUED",
            idempotency_key="key_unique_1"
        )
        db.add(audit2)
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.anyio
async def test_agent_finding_association_and_evidence():
    """Verify AgentFinding creation with structured JSON evidence."""
    async with TestAsyncSessionLocal() as db:
        pr = models.PullRequest(repository="org/repo", pr_number=5)
        db.add(pr)
        await db.commit()

        audit = models.AuditRun(
            pull_request_id=pr.id,
            commit_sha="sha_evidence",
            status="COMPLETED",
            idempotency_key="key_audit_finding",
            trust_score=88.5
        )
        db.add(audit)
        await db.commit()

        finding = models.AgentFinding(
            audit_run_id=audit.id,
            agent_name="FACT_CHECKER",
            severity="HIGH",
            status="OPEN",
            title="Hallucinated API in math module",
            description="Function does not exist in standard library.",
            file_path="math_utils.py",
            line_number=42,
            evidence={
                "called_api": "math.non_existent",
                "expected_signature": "None",
                "actual_arguments": [1, 2]
            }
        )
        db.add(finding)
        await db.commit()
        await db.refresh(finding)

        assert finding.id is not None
        assert finding.evidence["called_api"] == "math.non_existent"
        assert finding.agent_name == "FACT_CHECKER"


@pytest.mark.anyio
async def test_cascade_deletion():
    """Verify that deleting a PullRequest cascades to AuditRuns and AgentFindings."""
    async with TestAsyncSessionLocal() as db:
        pr = models.PullRequest(repository="cascade/test", pr_number=99)
        db.add(pr)
        await db.commit()

        audit = models.AuditRun(
            pull_request_id=pr.id,
            commit_sha="sha_cascade",
            idempotency_key="cascade_key"
        )
        db.add(audit)
        await db.commit()

        finding = models.AgentFinding(
            audit_run_id=audit.id,
            agent_name="SECURITY_GUARD",
            severity="CRITICAL",
            title="SQL Injection"
        )
        db.add(finding)
        await db.commit()

        # Delete PullRequest
        await db.delete(pr)
        await db.commit()

        # Verify AuditRun and AgentFinding are deleted
        audits_remain = (await db.execute(select(models.AuditRun))).scalars().all()
        findings_remain = (await db.execute(select(models.AgentFinding))).scalars().all()
        assert len(audits_remain) == 0
        assert len(findings_remain) == 0


@pytest.mark.anyio
async def test_get_audits_endpoint():
    """Verify GET /audits and GET /audits/{id} retrieve real audit records with findings."""
    async with TestAsyncSessionLocal() as db:
        pr = models.PullRequest(repository="test/repo", pr_number=7, latest_commit_sha="sha77")
        db.add(pr)
        await db.commit()

        audit = models.AuditRun(
            pull_request_id=pr.id,
            commit_sha="sha77",
            status="COMPLETED",
            trust_score=94.0,
            summary="All ground truth verified successfully.",
            recommendation="APPROVE",
            idempotency_key="get_audit_key"
        )
        db.add(audit)
        await db.commit()
        await db.refresh(audit)
        audit_uuid = str(audit.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /audits list
        res_list = await client.get("/audits")
        assert res_list.status_code == 200
        items = res_list.json()
        assert len(items) == 1
        assert items[0]["id"] == audit_uuid
        assert items[0]["trust_score"] == 94.0
        assert items[0]["pull_request"]["repository"] == "test/repo"

        # GET /audits/{id}
        res_single = await client.get(f"/audits/{audit_uuid}")
        assert res_single.status_code == 200
        single_item = res_single.json()
        assert single_item["id"] == audit_uuid
        assert single_item["status"] == "COMPLETED"

        # Not found 404
        random_uuid = str(uuid.uuid4())
        res_404 = await client.get(f"/audits/{random_uuid}")
        assert res_404.status_code == 404
