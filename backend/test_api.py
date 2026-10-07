import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from database import Base, get_db
import models

# Use SQLite in-memory for testing to avoid touching production db
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
test_engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=test_engine)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert "database_status" in response.json()

def test_get_audits_empty():
    response = client.get("/audits")
    assert response.status_code == 200
    assert response.json() == []

def test_get_audits_with_data():
    db = TestingSessionLocal()
    pr = models.PullRequest(repository_full_name="test/repo", pr_number=1, commit_sha="abc1234")
    db.add(pr)
    db.commit()
    
    audit = models.AuditRun(pull_request_id=pr.id, status="PENDING")
    db.add(audit)
    db.commit()

    finding = models.AgentFinding(audit_run_id=audit.id, agent_name="TestAgent", title="Test Finding", description="Desc")
    db.add(finding)
    db.commit()
    db.close()

    response = client.get("/audits")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["pull_request_id"] == 1
    assert len(data[0]["findings"]) == 1
    assert data[0]["findings"][0]["title"] == "Test Finding"

def test_get_audit_by_id():
    db = TestingSessionLocal()
    pr = models.PullRequest(repository_full_name="org/repo", pr_number=42, commit_sha="def5678")
    db.add(pr)
    db.commit()

    audit = models.AuditRun(pull_request_id=pr.id, status="COMPLETED", trust_score=92)
    db.add(audit)
    db.commit()
    audit_id = audit.id
    db.close()

    res = client.get(f"/audits/{audit_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == audit_id
    assert body["trust_score"] == 92
    assert body["status"] == "COMPLETED"

    # Test not found
    res_not_found = client.get("/audits/999999")
    assert res_not_found.status_code == 404
