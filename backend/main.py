import os
import sys
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure worker directory is on sys.path for Celery task importing
worker_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "worker"))
if worker_dir not in sys.path:
    sys.path.insert(0, worker_dir)

from database import async_engine, get_db
import models
import schemas

try:
    from celery_app import execute_audit_pipeline
except ImportError:
    execute_audit_pipeline = None

logger = logging.getLogger("sceptic.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(
    title="Sceptic Backend",
    description="Independent AI-Generated Code Verification System",
    version="0.1.0"
)


@app.get("/health")
async def health_check():
    """General health check endpoint."""
    return {
        "status": "ok",
        "message": "Backend is reachable"
    }


@app.get("/health/db")
async def health_db_check(db: AsyncSession = Depends(get_db)):
    """
    Dedicated database health check endpoint executing a lightweight query (SELECT 1).
    """
    try:
        result = await db.execute(text("SELECT 1"))
        scalar_val = result.scalar()
        return {
            "status": "healthy",
            "database": scalar_val
        }
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unreachable"
        )


@app.get("/audits", response_model=List[schemas.AuditRunResponse])
async def get_audits(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve paginated audit runs from PostgreSQL, including PR metadata and findings.
    """
    stmt = (
        select(models.AuditRun)
        .options(
            selectinload(models.AuditRun.pull_request),
            selectinload(models.AuditRun.findings)
        )
        .order_by(models.AuditRun.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    audits = result.scalars().all()
    return audits


@app.get("/audits/{audit_id}", response_model=schemas.AuditRunResponse)
async def get_audit(
    audit_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve a single audit run by UUID with all its findings and PR metadata.
    """
    stmt = (
        select(models.AuditRun)
        .options(
            selectinload(models.AuditRun.pull_request),
            selectinload(models.AuditRun.findings)
        )
        .filter(models.AuditRun.id == audit_id)
    )
    result = await db.execute(stmt)
    audit = result.scalars().first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit


@app.post("/webhook")
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Webhook Receiver for PR events with idempotency enforcement.
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
        title = pr_data.get("title")
        description = pr_data.get("body")
        author = pr_data.get("user", {}).get("login")
    else:
        pr_number = payload.get("pr_number")
        commit_sha = payload.get("commit_sha")
        branch_name = payload.get("branch_name")
        title = payload.get("title")
        description = payload.get("description")
        author = payload.get("author")

    # Validation
    if not repo_name or pr_number is None or not commit_sha:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: repository, pr_number, and commit_sha are mandatory."
        )

    logger.info(f"Webhook received: {repo_name} PR #{pr_number} (commit: {commit_sha})")

    # Retrieve or create PullRequest
    stmt = select(models.PullRequest).filter(
        models.PullRequest.repository == repo_name,
        models.PullRequest.pr_number == pr_number
    )
    result = await db.execute(stmt)
    pr = result.scalars().first()

    if not pr:
        pr = models.PullRequest(
            repository=repo_name,
            pr_number=pr_number,
            title=title,
            description=description,
            source_branch=branch_name,
            author=author,
            latest_commit_sha=commit_sha
        )
        db.add(pr)
        await db.commit()
        await db.refresh(pr)
    else:
        # Check idempotency: unique idempotency_key per repository + PR + commit
        idempotency_key = f"{repo_name}#{pr_number}@{commit_sha}"
        stmt_audit = select(models.AuditRun).filter(
            models.AuditRun.pull_request_id == pr.id,
            models.AuditRun.idempotency_key == idempotency_key
        ).order_by(models.AuditRun.created_at.desc())
        audit_res = await db.execute(stmt_audit)
        existing_audit = audit_res.scalars().first()

        if existing_audit:
            logger.info(f"Idempotency hit: AuditRun #{existing_audit.id} already exists for {idempotency_key}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "ALREADY_EXISTS",
                    "audit_run_id": str(existing_audit.id),
                    "pull_request_id": str(pr.id),
                    "message": "Audit for this commit is already in progress or completed."
                }
            )

        # Update latest commit info on existing PR
        pr.latest_commit_sha = commit_sha
        if branch_name:
            pr.source_branch = branch_name
        await db.commit()
        await db.refresh(pr)

    idempotency_key = f"{repo_name}#{pr_number}@{commit_sha}"

    # Create new AuditRun
    audit_run = models.AuditRun(
        pull_request_id=pr.id,
        commit_sha=commit_sha,
        status="QUEUED",
        idempotency_key=idempotency_key
    )
    db.add(audit_run)
    await db.commit()
    await db.refresh(audit_run)

    # Queue Celery task if broker available
    task_id = None
    if execute_audit_pipeline:
        try:
            task = execute_audit_pipeline.delay(str(audit_run.id), payload)
            task_id = task.id
            logger.info(f"Queued Celery task {task_id} for AuditRun {audit_run.id}")
        except Exception as e:
            logger.warning(f"Could not dispatch to Celery broker (offline in mock/test): {str(e)}")

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "QUEUED",
            "audit_run_id": str(audit_run.id),
            "pull_request_id": str(pr.id),
            "task_id": task_id
        }
    )
