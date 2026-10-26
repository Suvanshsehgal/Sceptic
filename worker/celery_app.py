import os
import sys
import logging
from datetime import datetime, timezone
from celery import Celery

# Ensure paths for backend and worker modules are available
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")
worker_dir = os.path.join(root_dir, "worker")
for p in [root_dir, backend_dir, worker_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from database import SessionLocal
import models
from orchestrator import AuditOrchestrator
from blind_tester import SpecificationMetadata
from crewai_reporter import post_pr_summary

logger = logging.getLogger("sceptic.celery")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "sceptic_worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True
)

def _post_pr_summary(payload: dict, report: dict) -> None:
    """Best-effort: publishes the verdict on the pull request. A failure here never fails the audit."""
    repo = payload.get("repository")
    if isinstance(repo, dict):
        repo = repo.get("full_name")
    pr_number = payload.get("pr_number")
    pr_data = payload.get("pull_request")
    if pr_number is None and isinstance(pr_data, dict):
        pr_number = pr_data.get("number")
    if not repo or pr_number is None:
        return
    body = (
        f"**Sceptic verdict: {report.get('recommendation')}** "
        f"(Trust Score {report.get('trust_score')}/100)\n\n{report.get('summary', '')}"
    )
    try:
        result = post_pr_summary(str(repo), int(pr_number), body)
        logger.info(f"PR summary for {repo}#{pr_number}: {result}")
    except Exception as e:
        logger.warning(f"Could not post PR summary for {repo}#{pr_number}: {e}")


@celery_app.task(name="execute_audit_pipeline", bind=True)
def execute_audit_pipeline(self, audit_run_id, payload: dict):
    """
    Asynchronous Celery task processing an audit run.
    """
    logger.info(f"Task started for AuditRun ID: {audit_run_id}")
    import uuid as uuid_pkg
    if isinstance(audit_run_id, str):
        try:
            audit_run_id = uuid_pkg.UUID(audit_run_id)
        except Exception:
            pass
    db = SessionLocal()
    try:
        audit_run = db.query(models.AuditRun).filter(models.AuditRun.id == audit_run_id).first()
        if not audit_run:
            logger.error(f"AuditRun with id {audit_run_id} not found in database.")
            return {"status": "error", "message": "AuditRun not found"}

        # Mark as RUNNING
        audit_run.status = "RUNNING"
        audit_run.started_at = datetime.now(timezone.utc)
        db.commit()

        # Extract audit details from payload
        source_code = payload.get("source_code") or payload.get("code") or ""
        function_name = payload.get("function_name") or "target_function"
        docstring = payload.get("docstring") or ""
        specification = payload.get("specification") or payload.get("description") or "Verify functional correctness and security."
        file_path = payload.get("file_path") or "target.py"

        spec = SpecificationMetadata(
            function_name=function_name,
            docstring=docstring,
            specification=specification
        )

        def record_progress(agent_name: str, finding_count: int) -> None:
            # Assign a new dict so SQLAlchemy detects the change on the JSON column.
            current = dict(audit_run.progress or {"stage": "RUNNING", "agents": {}})
            agents = dict(current.get("agents", {}))
            agents[agent_name] = {"status": "done", "findings": finding_count}
            audit_run.progress = {
                "stage": "RUNNING",
                "agents": agents,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            db.commit()

        audit_run.progress = {"stage": "RUNNING", "agents": {}, "updated_at": datetime.now(timezone.utc).isoformat()}
        db.commit()

        orchestrator = AuditOrchestrator()
        report = orchestrator.run_pipeline(
            source_code=source_code,
            specification_metadata=spec,
            file_path=file_path,
            progress_callback=record_progress,
        )

        # Persist AgentFindings
        for f in report.get("all_findings", []):
            evidence_val = f.get("evidence")
            if not evidence_val:
                evidence_val = {"contextual_analysis": str(f.get("contextual_analysis") or "")}
            elif isinstance(evidence_val, str):
                evidence_val = {"detail": evidence_val}

            agent_finding = models.AgentFinding(
                audit_run_id=audit_run.id,
                agent_name=f.get("agent_name", "Unknown-Agent"),
                severity=f.get("severity", "INFO"),
                title=f.get("title", "Finding"),
                description=f.get("description", ""),
                file_path=f.get("file_path", file_path),
                line_number=f.get("line_number"),
                evidence=evidence_val,
                recommendation=f.get("recommendation", "")
            )
            db.add(agent_finding)

        # Update AuditRun record with Trust Score and summary
        audit_run.status = "COMPLETED"
        audit_run.completed_at = datetime.now(timezone.utc)
        audit_run.trust_score = report.get("trust_score")
        audit_run.summary = report.get("summary")
        audit_run.recommendation = report.get("recommendation")
        db.commit()

        logger.info(f"AuditRun {audit_run_id} completed successfully. Score: {audit_run.trust_score}")
        _post_pr_summary(payload, report)
        return {
            "status": "COMPLETED",
            "audit_run_id": audit_run_id,
            "trust_score": audit_run.trust_score,
            "recommendation": audit_run.recommendation
        }

    except Exception as e:
        logger.exception(f"AuditRun {audit_run_id} failed: {str(e)}")
        db.rollback()
        try:
            audit_run = db.query(models.AuditRun).filter(models.AuditRun.id == audit_run_id).first()
            if audit_run:
                audit_run.status = "FAILED"
                audit_run.completed_at = datetime.now(timezone.utc)
                audit_run.summary = f"Audit execution failed: {str(e)}"
                audit_run.recommendation = "BLOCK"
                db.commit()
        except Exception as inner_e:
            logger.error(f"Failed to record failure status for AuditRun {audit_run_id}: {str(inner_e)}")
        return {"status": "FAILED", "error": str(e)}
    finally:
        db.close()
