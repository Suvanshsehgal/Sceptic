import os
import sys
import logging
import psycopg2
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Any

# Ensure worker directory is on sys.path for Celery task importing
worker_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "worker"))
if worker_dir not in sys.path:
    sys.path.insert(0, worker_dir)

from database import engine, get_db
import models
import schemas

try:
    from celery_app import execute_audit_pipeline
except ImportError:
    execute_audit_pipeline = None

logger = logging.getLogger("sceptic.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

class Config:
    DATABASE_URL = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = FastAPI(title="Sceptic Backend - Phase 5")

@app.get("/health")
def health_check():
    db_status = "not configured"
    
    if Config.DATABASE_URL:
        try:
            conn = psycopg2.connect(Config.DATABASE_URL, connect_timeout=3)
            conn.close()
            db_status = "connected successfully"
        except Exception as e:
            db_status = f"connection failed: {str(e)}"

    return {
        "status": "ok",
        "database_status": db_status,
        "redis_configured": bool(Config.REDIS_URL),
        "message": "Backend is reachable"
    }

@app.get("/audits", response_model=List[schemas.AuditRunResponse])
def get_audits(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    audits = db.query(models.AuditRun).order_by(models.AuditRun.id.desc()).offset(skip).limit(limit).all()
    return audits

@app.get("/audits/{audit_id}", response_model=schemas.AuditRunResponse)
def get_audit(audit_id: int, db: Session = Depends(get_db)):
    audit = db.query(models.AuditRun).filter(models.AuditRun.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit

@app.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Phase 5 Webhook Receiver.
    Validates payload, enforces idempotency, creates PullRequest & AuditRun records,
    and dispatches asynchronous Celery task.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Extract repository information
    repo = payload.get("repository")
    if isinstance(repo, dict):
        repo_name = repo.get("full_name") or repo.get("name")
    else:
        repo_name = repo

    # Extract pull request & commit information
    pr_data = payload.get("pull_request")
    if isinstance(pr_data, dict):
        pr_number = pr_data.get("number")
        commit_sha = pr_data.get("head", {}).get("sha")
        branch_name = pr_data.get("head", {}).get("ref")
    else:
        pr_number = payload.get("pr_number")
        commit_sha = payload.get("commit_sha")
        branch_name = payload.get("branch_name")

    # Validation
    if not repo_name or pr_number is None or not commit_sha:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: repository, pr_number, and commit_sha are mandatory."
        )

    logger.info(f"Webhook received: {repo_name} PR #{pr_number} (commit: {commit_sha})")

    # Retrieve or create PullRequest
    pr = db.query(models.PullRequest).filter(
        models.PullRequest.repository_full_name == repo_name,
        models.PullRequest.pr_number == pr_number
    ).first()

    if not pr:
        pr = models.PullRequest(
            repository_full_name=repo_name,
            pr_number=pr_number,
            commit_sha=commit_sha,
            branch_name=branch_name
        )
        db.add(pr)
        db.commit()
        db.refresh(pr)
    else:
        # Idempotency check: if an active or completed audit already exists for this exact commit
        existing_audit = db.query(models.AuditRun).filter(
            models.AuditRun.pull_request_id == pr.id,
            models.AuditRun.status.in_(["PENDING", "RUNNING", "COMPLETED"])
        ).order_by(models.AuditRun.id.desc()).first()

        if existing_audit and pr.commit_sha == commit_sha:
            logger.info(f"Idempotency hit: AuditRun #{existing_audit.id} already exists for commit {commit_sha}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "ALREADY_EXISTS",
                    "audit_run_id": existing_audit.id,
                    "pull_request_id": pr.id,
                    "message": "Audit for this commit is already in progress or completed."
                }
            )

        # Update commit if changed
        pr.commit_sha = commit_sha
        pr.branch_name = branch_name or pr.branch_name
        db.commit()
        db.refresh(pr)

    # Create new AuditRun
    audit_run = models.AuditRun(
        pull_request_id=pr.id,
        status="PENDING"
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)

    # Queue Celery task
    task_id = None
    if execute_audit_pipeline:
        try:
            task = execute_audit_pipeline.delay(audit_run.id, payload)
            task_id = task.id
            logger.info(f"Queued Celery task {task_id} for AuditRun {audit_run.id}")
        except Exception as e:
            logger.warning(f"Could not dispatch to Celery broker (offline in mock/test): {str(e)}")

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "QUEUED",
            "audit_run_id": audit_run.id,
            "pull_request_id": pr.id,
            "task_id": task_id
        }
    )
