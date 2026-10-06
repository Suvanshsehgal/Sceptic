import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add paths
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")
worker_dir = os.path.join(root_dir, "worker")
for p in [root_dir, backend_dir, worker_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from main import app
from database import Base, get_db
import models
from synthesizer import TrustScoreCalculator, ReportSynthesizer
from orchestrator import AuditOrchestrator
from blind_tester import SpecificationMetadata
import celery_app

# SQLite test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_phase5.db"
test_engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    orig_session = celery_app.SessionLocal
    celery_app.SessionLocal = TestingSessionLocal
    yield
    celery_app.SessionLocal = orig_session
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists("./test_phase5.db"):
        try:
            os.remove("./test_phase5.db")
        except Exception:
            pass

# ========================================================
# A. CREWAI ORCHESTRATION & FAN-OUT / FAN-IN TESTS
# ========================================================

def test_orchestrator_invokes_all_three_agents():
    """
    Verifies that the orchestrator executes Fact-Checker, Blind-Tester,
    and Security-Guard independently, and synthesizes results.
    """
    code = """
import os

def calculate_total(price, tax):
    return price + tax

total = calculate_total(10, 20)
"""
    spec = SpecificationMetadata(
        function_name="calculate_total",
        docstring="Adds tax to price.",
        specification="Price and tax are positive floats."
    )
    orchestrator = AuditOrchestrator()
    report = orchestrator.run_pipeline(code, spec, file_path="target.py")

    assert "trust_score" in report
    assert "recommendation" in report
    assert "severity_breakdown" in report
    assert "agent_contributions" in report
    assert report["agent_contributions"]["Fact-Checker"] >= 1
    assert report["agent_contributions"]["Blind-Tester"] >= 1
    assert report["agent_contributions"]["Security-Guard"] >= 1

def test_trust_score_calculator_deterministic_methodology():
    """
    Tests the deterministic Trust Score calculation and penalty weighting.
    """
    clean_findings = [
        {"agent_name": "Fact-Checker", "severity": "INFO", "status": "VALID", "title": "Valid API"},
        {"agent_name": "Blind-Tester", "severity": "INFO", "status": "PASS", "title": "Passed Tests"},
        {"agent_name": "Security-Guard", "severity": "INFO", "status": "VALID", "title": "Clean Scan"}
    ]
    res_clean = TrustScoreCalculator.calculate(clean_findings)
    assert res_clean["trust_score"] == 100
    assert res_clean["recommendation"] == "APPROVE"

    # High severity + critical severity deduction: 100 - 35 (critical) - 20 (high) = 45
    bad_findings = [
        {"agent_name": "Security-Guard", "severity": "CRITICAL", "status": "INVALID", "title": "RCE"},
        {"agent_name": "Blind-Tester", "severity": "HIGH", "status": "FAIL", "title": "Test Failure"}
    ]
    res_bad = TrustScoreCalculator.calculate(bad_findings)
    assert res_bad["trust_score"] == 45
    assert res_bad["recommendation"] == "BLOCK"

# ========================================================
# B. BLIND TESTER ISOLATION
# ========================================================

def test_blind_tester_information_isolation_preserved_in_orchestration():
    """
    Verifies that if implementation or other agent findings are leaked
    into the specification metadata, isolation validation strictly raises ValueError.
    """
    leaked_spec = SpecificationMetadata(
        function_name="test_func",
        docstring="Docstring",
        specification="Spec",
        approved_metadata={"fact_checker_findings": "Leaked data"}
    )
    orchestrator = AuditOrchestrator()
    # Leaked metadata triggers error finding in Blind Tester without crashing orchestrator
    report = orchestrator.run_pipeline("def test_func(): pass", leaked_spec)
    assert any("isolation violation" in f.get("description", "").lower() for f in report["all_findings"])

# ========================================================
# C. CELERY AUDIT TASK EXECUTION
# ========================================================

def test_celery_task_success_updates_audit_run():
    db = TestingSessionLocal()
    pr = models.PullRequest(repository_full_name="org/repo", pr_number=10, commit_sha="sha123")
    db.add(pr)
    db.commit()

    audit_run = models.AuditRun(pull_request_id=pr.id, status="PENDING")
    db.add(audit_run)
    db.commit()
    audit_id = audit_run.id
    db.close()

    payload = {
        "source_code": "def hello(): return 'world'",
        "function_name": "hello",
        "docstring": "Returns world.",
        "specification": "Must return string 'world'."
    }

    # Execute task synchronously
    result = celery_app.execute_audit_pipeline(audit_id, payload)
    assert result["status"] == "COMPLETED"

    # Verify DB update
    db = TestingSessionLocal()
    updated = db.query(models.AuditRun).filter(models.AuditRun.id == audit_id).first()
    assert updated.status == "COMPLETED"
    assert updated.trust_score is not None
    assert updated.completed_at is not None
    assert updated.summary is not None
    findings = db.query(models.AgentFinding).filter(models.AgentFinding.audit_run_id == audit_id).all()
    assert len(findings) > 0
    db.close()

def test_celery_task_failure_updates_audit_run():
    db = TestingSessionLocal()
    pr = models.PullRequest(repository_full_name="org/repo", pr_number=11, commit_sha="sha999")
    db.add(pr)
    db.commit()

    audit_run = models.AuditRun(pull_request_id=pr.id, status="PENDING")
    db.add(audit_run)
    db.commit()
    audit_id = audit_run.id
    db.close()

    # Pass invalid payload that forces an unhandled exception inside task
    with patch("orchestrator.AuditOrchestrator.run_pipeline", side_effect=RuntimeError("Simulated pipeline crash")):
        res = celery_app.execute_audit_pipeline(audit_id, {"source_code": "pass"})
        assert res["status"] == "FAILED"

    # Verify audit is NOT left in RUNNING state
    db = TestingSessionLocal()
    failed = db.query(models.AuditRun).filter(models.AuditRun.id == audit_id).first()
    assert failed.status == "FAILED"
    assert "Simulated pipeline crash" in failed.summary
    db.close()

# ========================================================
# D & E. WEBHOOK VALIDATION, QUEUING & IDEMPOTENCY
# ========================================================

def test_webhook_invalid_payload_rejected():
    # Missing repository, pr_number, commit_sha
    resp = client.post("/webhook", json={"invalid": "payload"})
    assert resp.status_code == 400
    assert "Missing required fields" in resp.json()["detail"]

def test_webhook_valid_payload_accepted():
    payload = {
        "repository": "facebook/react",
        "pr_number": 101,
        "commit_sha": "commit_abc1",
        "branch_name": "feature-x"
    }
    with patch("main.execute_audit_pipeline.delay", return_value=MagicMock(id="celery-mock-id")):
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "QUEUED"
        assert "audit_run_id" in data

def test_webhook_idempotency_prevents_duplicate_audits():
    payload = {
        "repository": "pallets/flask",
        "pr_number": 42,
        "commit_sha": "commit_stable_sha",
        "branch_name": "main"
    }
    with patch("main.execute_audit_pipeline.delay", return_value=MagicMock(id="mock-1")):
        # First request
        resp1 = client.post("/webhook", json=payload)
        assert resp1.status_code == 202
        audit_id_1 = resp1.json()["audit_run_id"]

        # Second request with exact same repository, PR, and commit_sha
        resp2 = client.post("/webhook", json=payload)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "ALREADY_EXISTS"
        assert data2["audit_run_id"] == audit_id_1

# ========================================================
# F & G. COMPLETE END-TO-END FLOW
# ========================================================

def test_complete_end_to_end_flow():
    """
    Webhook -> AuditRun -> Celery -> CrewAI Orchestration -> DB Persistence
    """
    payload = {
        "repository": "openai/whisper",
        "pr_number": 77,
        "commit_sha": "whisper_sha_123",
        "branch_name": "fix-audio",
        "source_code": "import os\ndef join_paths(a, b):\n    return os.path.join(a, b)",
        "function_name": "join_paths",
        "docstring": "Joins two path strings safely.",
        "specification": "Must return os.path.join(a, b)."
    }

    # 1. Send Webhook (mocking async broker dispatch so test is deterministic and fast)
    with patch("main.execute_audit_pipeline.delay", return_value=MagicMock(id="task-mock-123")):
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 202
        audit_run_id = resp.json()["audit_run_id"]

    # 2. Run Celery execution
    task_res = celery_app.execute_audit_pipeline(audit_run_id, payload)
    assert task_res["status"] == "COMPLETED"

    # 3. Verify Database Persistence via API
    resp_audits = client.get("/audits")
    assert resp_audits.status_code == 200
    audits = resp_audits.json()
    matching = [a for a in audits if a["id"] == audit_run_id]
    assert len(matching) == 1
    audit_data = matching[0]
    assert audit_data["status"] == "COMPLETED"
    assert audit_data["trust_score"] is not None
    assert audit_data["recommendation"] in ["APPROVE", "REQUEST_CHANGES", "BLOCK"]
    assert len(audit_data["findings"]) > 0
