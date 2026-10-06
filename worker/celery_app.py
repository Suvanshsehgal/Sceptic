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

@celery_app.task(name="execute_audit_pipeline", bind=True)
def execute_audit_pipeline(self, audit_run_id: int, payload: dict):
    """
    Asynchronous Celery task processing an audit run.
    """
    logger.info(f"Task started for AuditRun ID: {audit_run_id}")
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

        orchestrator = AuditOrchestrator()
        report = orchestrator.run_pipeline(
            source_code=source_code,
            specification_metadata=spec,
            file_path=file_path
        )

        # Persist AgentFindings
        for f in report.get("all_findings", []):
            agent_finding = models.AgentFinding(
                audit_run_id=audit_run.id,
                agent_name=f.get("agent_name", "Unknown-Agent"),
                severity=f.get("severity", "INFO"),
                title=f.get("title", "Finding"),
                description=f.get("description", ""),
                file_path=f.get("file_path", file_path),
                line_number=f.get("line_number"),
                evidence=f.get("evidence") or str(f.get("contextual_analysis") or "")
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
