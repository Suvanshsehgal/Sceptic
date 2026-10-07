import os
import sys
import logging
import secrets
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, status, Request, Query
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure backend and worker directories are on sys.path
backend_dir = os.path.abspath(os.path.dirname(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

worker_dir = os.path.abspath(os.path.join(backend_dir, "..", "worker"))
if worker_dir not in sys.path:
    sys.path.insert(0, worker_dir)

from database import async_engine, get_db
import models
import schemas
from auth import (
    create_access_token,
    get_current_user,
    get_optional_current_user,
    get_google_auth_url,
    exchange_google_code_for_user_info,
    hash_password,
    verify_password,
    GOOGLE_CLIENT_ID
)
from feature_scoper import evaluate_feature_proposal

try:
    from celery_app import execute_audit_pipeline
except ImportError:
    execute_audit_pipeline = None

logger = logging.getLogger("sceptic.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database schema has hashed_password column
    try:
        async with async_engine.begin() as conn:
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password VARCHAR(255);"))
        logger.info("Database schema verified: users.hashed_password column is present.")
    except Exception as e:
        logger.warning(f"Could not verify users.hashed_password column: {e}")
    yield


app = FastAPI(
    title="Sceptic Backend",
    description="Independent AI-Generated Code Verification System",
    version="0.2.0",
    lifespan=lifespan
)

# Enable CORS for web frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Temporary in-memory state store for CSRF validation during OAuth flow
oauth_states = {}


# ========================================================
# 1. HEALTH CHECKS
# ========================================================

@app.get("/health")
async def health_check():
    """General health check endpoint."""
    return {
        "status": "ok",
        "message": "Backend is reachable",
        "database_status": "Connected (PostgreSQL)",
        "redis_configured": bool(os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL"))
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


# ========================================================
# 2. AUTHENTICATION & GOOGLE OAUTH ROUTES
# ========================================================

@app.get("/auth/google/login")
async def google_login(redirect_uri: Optional[str] = None):
    """
    Generates the Google OAuth authorization URL.
    Returns JSON with the URL, or can redirect directly.
    """
    state = secrets.token_urlsafe(32)
    oauth_states[state] = {"created_at": secrets.token_hex(8), "redirect_uri": redirect_uri}
    auth_url = get_google_auth_url(state=state, redirect_uri=redirect_uri)
    return {
        "auth_url": auth_url,
        "state": state
    }


@app.get("/auth/google/callback")
async def google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    mock_email: Optional[str] = None,
    mock_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Handles the Google OAuth redirect callback.
    Exchange code for user profile, links/creates User and AuthAccount, and issues JWT.
    Supports a mock parameter for hermetic test execution without external networks.
    """
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")

    user_info = None
    if mock_email:
        # Hermetic testing bypass
        user_info = {
            "sub": f"mock-sub-{mock_email}",
            "email": mock_email,
            "name": mock_name or mock_email.split("@")[0],
            "picture": "https://lh3.googleusercontent.com/mock-avatar.png"
        }
    else:
        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing authorization code or state")

        if state not in oauth_states:
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

        saved_state = oauth_states.pop(state)
        redirect_uri = saved_state.get("redirect_uri")

        try:
            user_info = await exchange_google_code_for_user_info(code, redirect_uri=redirect_uri)
        except Exception as e:
            logger.error(f"Failed to exchange Google OAuth code: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Google authentication failed: {str(e)}")

    email = user_info.get("email")
    name = user_info.get("name") or email.split("@")[0]
    avatar_url = user_info.get("picture")
    google_sub = user_info.get("sub")

    if not email or not google_sub:
        raise HTTPException(status_code=400, detail="Incomplete profile returned from Google")

    # Find or create User
    stmt_user = select(models.User).filter(models.User.email == email)
    res_user = await db.execute(stmt_user)
    user = res_user.scalars().first()

    if not user:
        user = models.User(
            name=name,
            email=email,
            avatar_url=avatar_url
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Find or create AuthAccount
    stmt_account = select(models.AuthAccount).filter(
        models.AuthAccount.provider == "google",
        models.AuthAccount.provider_account_id == google_sub
    )
    res_account = await db.execute(stmt_account)
    auth_account = res_account.scalars().first()

    if not auth_account:
        auth_account = models.AuthAccount(
            user_id=user.id,
            provider="google",
            provider_account_id=google_sub
        )
        db.add(auth_account)
        await db.commit()

    # Issue access token
    access_token = create_access_token(data={"sub": str(user.id), "email": user.email, "name": user.name})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat()
        }
    }


@app.post("/auth/register", response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: schemas.UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user account with email and password.
    Shares the same profile with Google OAuth users.
    """
    clean_email = payload.email.strip().lower()
    clean_name = payload.name.strip()

    if not clean_email or "@" not in clean_email:
        raise HTTPException(status_code=400, detail="Invalid email address.")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long.")

    stmt = select(models.User).filter(models.User.email == clean_email)
    res = await db.execute(stmt)
    existing_user = res.scalars().first()

    if existing_user:
        if existing_user.hashed_password:
            raise HTTPException(status_code=400, detail="An account with this email already exists. Please log in.")
        else:
            # User previously logged in via Google OAuth. Link password to this existing account!
            existing_user.hashed_password = hash_password(payload.password)
            if clean_name and not existing_user.name:
                existing_user.name = clean_name
            await db.commit()
            await db.refresh(existing_user)
            access_token = create_access_token(
                data={"sub": str(existing_user.id), "email": existing_user.email, "name": existing_user.name}
            )
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "user": existing_user
            }

    # Create new User
    user = models.User(
        name=clean_name or clean_email.split("@")[0],
        email=clean_email,
        hashed_password=hash_password(payload.password)
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Automatically create default project for this user
    default_proj = models.Project(
        user_id=user.id,
        name=f"{user.name}'s Project",
        description="Default project created on registration"
    )
    db.add(default_proj)
    await db.commit()

    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "name": user.name}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


@app.post("/auth/login", response_model=schemas.TokenResponse)
async def login(
    payload: schemas.UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate an existing user with email and password.
    Returns JWT access token and user profile.
    """
    clean_email = payload.email.strip().lower()

    stmt = select(models.User).filter(models.User.email == clean_email)
    res = await db.execute(stmt)
    user = res.scalars().first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not user.hashed_password:
        raise HTTPException(
            status_code=400,
            detail="This account was registered using Google. Please log in with Google, or register a password."
        )

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "name": user.name}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


@app.get("/auth/me", response_model=schemas.UserResponse)
async def get_me(current_user: models.User = Depends(get_current_user)):
    """Retrieve profile of currently authenticated user."""
    return current_user


# ========================================================
# 3. PROJECT ROUTES (USER-OWNED)
# ========================================================

@app.get("/projects", response_model=List[schemas.ProjectResponse])
async def list_projects(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all projects owned by the authenticated user."""
    stmt = (
        select(models.Project)
        .filter(models.Project.user_id == current_user.id)
        .order_by(models.Project.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@app.post("/projects", response_model=schemas.ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: schemas.ProjectCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new project owned by the authenticated user."""
    # Check if a project with this name or repo URL already exists for the user
    stmt = select(models.Project).filter(
        models.Project.user_id == current_user.id,
        models.Project.name == project_in.name
    )
    result = await db.execute(stmt)
    existing = result.scalars().first()
    if existing:
        return existing

    new_project = models.Project(
        user_id=current_user.id,
        name=project_in.name,
        repository_url=project_in.repository_url,
        default_branch=project_in.default_branch or "main",
        description=project_in.description
    )
    db.add(new_project)
    await db.commit()
    await db.refresh(new_project)
    return new_project


@app.get("/projects/{project_id}", response_model=schemas.ProjectResponse)
async def get_project(
    project_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve a project by ID, strictly enforcing user ownership."""
    stmt = select(models.Project).filter(
        models.Project.id == project_id,
        models.Project.user_id == current_user.id
    )
    result = await db.execute(stmt)
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/projects/{project_id}/audits", response_model=List[schemas.AuditRunResponse])
async def list_project_audits(
    project_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve all audit runs belonging to a user's project."""
    # Verify project ownership
    stmt_p = select(models.Project).filter(
        models.Project.id == project_id,
        models.Project.user_id == current_user.id
    )
    res_p = await db.execute(stmt_p)
    if not res_p.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    stmt = (
        select(models.AuditRun)
        .join(models.PullRequest, models.AuditRun.pull_request_id == models.PullRequest.id)
        .filter(models.PullRequest.project_id == project_id)
        .options(
            selectinload(models.AuditRun.pull_request),
            selectinload(models.AuditRun.findings)
        )
        .order_by(models.AuditRun.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@app.post("/projects/{project_id}/audits", response_model=schemas.AuditRunResponse, status_code=status.HTTP_201_CREATED)
async def create_cli_audit(
    project_id: UUID,
    payload: schemas.CLIAuditSubmission,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Save an in-process CLI verification audit run and findings to PostgreSQL."""
    # 1. Verify project ownership
    stmt_p = select(models.Project).filter(
        models.Project.id == project_id,
        models.Project.user_id == current_user.id
    )
    res_p = await db.execute(stmt_p)
    project = res_p.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Get or create a PullRequest record for CLI audits in this project
    repo_name = project.name.replace(" ", "-").lower()
    stmt_pr = select(models.PullRequest).filter(
        models.PullRequest.project_id == project_id,
        models.PullRequest.repository == repo_name
    ).order_by(models.PullRequest.created_at.desc())
    res_pr = await db.execute(stmt_pr)
    pr = res_pr.scalars().first()

    if not pr:
        pr = models.PullRequest(
            project_id=project_id,
            repository=repo_name,
            pr_number=1,
            title=f"CLI Audit: {project.name}",
            description=f"Automated CLI audits for {project.name}",
            latest_commit_sha=payload.commit_sha or "cli-head",
            author=current_user.name
        )
        db.add(pr)
        await db.commit()
        await db.refresh(pr)

    # 3. Create completed AuditRun
    now = datetime.now(timezone.utc)
    idempotency_key = f"cli_{uuid.uuid4().hex[:12]}"
    audit_run = models.AuditRun(
        pull_request_id=pr.id,
        commit_sha=payload.commit_sha or "cli-head",
        status="COMPLETED",
        trust_score=payload.trust_score,
        summary=payload.summary or f"CLI verification completed with trust score {payload.trust_score:.1f}%",
        recommendation=payload.recommendation or "APPROVE",
        idempotency_key=idempotency_key,
        created_at=now,
        started_at=now,
        completed_at=now
    )
    db.add(audit_run)
    await db.commit()
    await db.refresh(audit_run)

    # 4. Add findings
    for f in payload.findings:
        agent_name = f.get("agent_name") or f.get("agent") or "verifier"
        sev = (f.get("severity") or "INFO").upper()
        title = f.get("title") or f.get("message") or f.get("called_api") or "Verification finding"
        desc = f.get("description") or str(f.get("evidence", ""))
        fp = f.get("file_path") or payload.target_path
        ln = f.get("line_number")
        ev = f.get("evidence")
        if isinstance(ev, (dict, list)):
            ev_data = ev
        elif ev is not None:
            ev_data = {"raw": str(ev)}
        else:
            ev_data = None

        finding_rec = models.AgentFinding(
            audit_run_id=audit_run.id,
            agent_name=agent_name,
            severity=sev,
            status="OPEN",
            title=str(title)[:500],
            description=desc,
            file_path=str(fp)[:1000] if fp else None,
            line_number=ln if isinstance(ln, int) else None,
            evidence=ev_data,
            recommendation=f.get("recommendation")
        )
        db.add(finding_rec)

    await db.commit()

    # Re-fetch with relationships loaded
    stmt_full = (
        select(models.AuditRun)
        .options(
            selectinload(models.AuditRun.pull_request),
            selectinload(models.AuditRun.findings)
        )
        .filter(models.AuditRun.id == audit_run.id)
    )
    res_full = await db.execute(stmt_full)
    return res_full.scalars().first()


# ========================================================
# 4. FEATURE ANALYSIS ROUTES
# ========================================================

@app.post("/projects/{project_id}/feature-analyses", response_model=schemas.FeatureAnalysisResponse, status_code=status.HTTP_201_CREATED)
async def create_feature_analysis(
    project_id: UUID,
    analysis_in: schemas.FeatureAnalysisCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates and stores a feature analysis for a project.
    Used by `sceptic newfeature` and Web UI.
    """
    # Verify ownership
    stmt_p = select(models.Project).filter(
        models.Project.id == project_id,
        models.Project.user_id == current_user.id
    )
    res_p = await db.execute(stmt_p)
    project = res_p.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    desc = analysis_in.feature_description

    # Dynamic evaluation using Groq LLM (openai/gpt-oss-120b) or semantic fallback
    eval_result = await evaluate_feature_proposal(
        feature_description=desc,
        project_name=project.name,
        project_description=project.description,
        repository_url=project.repository_url
    )

    analysis_record = models.FeatureAnalysis(
        project_id=project.id,
        user_id=current_user.id,
        feature_description=desc,
        feasibility_score=eval_result["feasibility_score"],
        complexity_score=eval_result["complexity_score"],
        risk_score=eval_result["risk_score"],
        confidence_score=eval_result["confidence_score"],
        analysis=eval_result["analysis"],
        implementation_plan=eval_result["implementation_plan"]
    )

    db.add(analysis_record)
    await db.commit()
    await db.refresh(analysis_record)
    return analysis_record


@app.get("/projects/{project_id}/feature-analyses", response_model=List[schemas.FeatureAnalysisResponse])
async def list_project_feature_analyses(
    project_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all feature analyses for a project."""
    stmt_p = select(models.Project).filter(
        models.Project.id == project_id,
        models.Project.user_id == current_user.id
    )
    res_p = await db.execute(stmt_p)
    if not res_p.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    stmt = (
        select(models.FeatureAnalysis)
        .filter(models.FeatureAnalysis.project_id == project_id)
        .order_by(models.FeatureAnalysis.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@app.get("/feature-analyses/{analysis_id}", response_model=schemas.FeatureAnalysisResponse)
async def get_feature_analysis(
    analysis_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get single feature analysis detail with ownership check."""
    stmt = select(models.FeatureAnalysis).filter(
        models.FeatureAnalysis.id == analysis_id,
        models.FeatureAnalysis.user_id == current_user.id
    )
    result = await db.execute(stmt)
    record = result.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="Feature analysis not found")
    return record


# ========================================================
# 5. AUDIT RUN ROUTES
# ========================================================

@app.get("/audits", response_model=List[schemas.AuditRunResponse])
async def get_audits(
    skip: int = 0,
    limit: int = 100,
    project_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve paginated audit runs from PostgreSQL.
    Optionally filters by project_id.
    """
    stmt = (
        select(models.AuditRun)
        .options(
            selectinload(models.AuditRun.pull_request),
            selectinload(models.AuditRun.findings)
        )
    )

    if project_id:
        stmt = stmt.join(models.PullRequest, models.AuditRun.pull_request_id == models.PullRequest.id).filter(
            models.PullRequest.project_id == project_id
        )

    stmt = stmt.order_by(models.AuditRun.created_at.desc()).offset(skip).limit(limit)
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

    # Optional project linkage
    project_id_str = payload.get("project_id")
    project_id = None
    if project_id_str:
        try:
            project_id = UUID(str(project_id_str))
        except ValueError:
            pass

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
            latest_commit_sha=commit_sha,
            project_id=project_id
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
        if project_id and not pr.project_id:
            pr.project_id = project_id
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


# ========================================================
# 7. DEPLOYMENT & OBSERVABILITY ROUTES (PHASE 10)
# ========================================================

async def _get_authorized_project(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession
) -> models.Project:
    """Helper to verify and return a user's owned project."""
    stmt = select(models.Project).filter(
        models.Project.id == project_id,
        models.Project.user_id == user_id
    )
    res = await db.execute(stmt)
    project = res.scalars().first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    return project


async def _get_authorized_deployment(
    deployment_id: UUID,
    user_id: UUID,
    db: AsyncSession
) -> models.Deployment:
    """Helper to verify and return a deployment belonging to a user's project."""
    stmt = (
        select(models.Deployment)
        .join(models.Project, models.Deployment.project_id == models.Project.id)
        .filter(
            models.Deployment.id == deployment_id,
            models.Project.user_id == user_id
        )
    )
    res = await db.execute(stmt)
    deployment = res.scalars().first()
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found"
        )
    return deployment


@app.post(
    "/projects/{project_id}/deployments",
    response_model=schemas.DeploymentResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_deployment(
    project_id: UUID,
    payload: schemas.DeploymentCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new deployment under an authorized project.
    Strictly verifies user ownership through Project -> User.
    """
    await _get_authorized_project(project_id, current_user.id, db)

    # If previous_deployment_id is provided, verify it belongs to this project
    if payload.previous_deployment_id:
        prev_stmt = select(models.Deployment).filter(
            models.Deployment.id == payload.previous_deployment_id,
            models.Deployment.project_id == project_id
        )
        prev_res = await db.execute(prev_stmt)
        if not prev_res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="previous_deployment_id must refer to a deployment within the same project"
            )

    deployment = models.Deployment(
        project_id=project_id,
        commit_sha=payload.commit_sha,
        image_name=payload.image_name,
        image_tag=payload.image_tag,
        image_digest=payload.image_digest,
        environment=payload.environment,
        version=payload.version,
        status=payload.status.value if hasattr(payload.status, "value") else str(payload.status),
        deployed_at=payload.deployed_at,
        completed_at=payload.completed_at,
        previous_deployment_id=payload.previous_deployment_id
    )
    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)
    return deployment


@app.get(
    "/projects/{project_id}/deployments",
    response_model=List[schemas.DeploymentResponse]
)
async def list_project_deployments(
    project_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all deployments under an authorized project.
    """
    await _get_authorized_project(project_id, current_user.id, db)

    stmt = (
        select(models.Deployment)
        .filter(models.Deployment.project_id == project_id)
        .order_by(models.Deployment.created_at.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()


@app.get(
    "/deployments/{deployment_id}",
    response_model=schemas.DeploymentResponse
)
async def get_deployment(
    deployment_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve deployment details by ID.
    Strictly verifies ownership through Deployment -> Project -> User.
    """
    return await _get_authorized_deployment(deployment_id, current_user.id, db)


@app.patch(
    "/deployments/{deployment_id}/status",
    response_model=schemas.DeploymentResponse
)
async def update_deployment_status(
    deployment_id: UUID,
    payload: schemas.DeploymentStatusUpdate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update the lifecycle status and timestamps of an authorized deployment.
    """
    deployment = await _get_authorized_deployment(deployment_id, current_user.id, db)
    deployment.status = payload.status.value if hasattr(payload.status, "value") else str(payload.status)
    if payload.deployed_at is not None:
        deployment.deployed_at = payload.deployed_at
    if payload.completed_at is not None:
        deployment.completed_at = payload.completed_at
    await db.commit()
    await db.refresh(deployment)
    return deployment


@app.get(
    "/deployments/{deployment_id}/telemetry",
    response_model=List[schemas.TelemetrySnapshotResponse]
)
async def list_deployment_telemetry(
    deployment_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List telemetry observations for an authorized deployment.
    """
    await _get_authorized_deployment(deployment_id, current_user.id, db)

    stmt = (
        select(models.TelemetrySnapshot)
        .filter(models.TelemetrySnapshot.deployment_id == deployment_id)
        .order_by(models.TelemetrySnapshot.timestamp.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()


@app.post(
    "/deployments/{deployment_id}/telemetry",
    response_model=schemas.TelemetrySnapshotResponse,
    status_code=status.HTTP_201_CREATED
)
async def record_telemetry_snapshot(
    deployment_id: UUID,
    payload: schemas.TelemetrySnapshotCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Record a new telemetry observation for an authorized deployment.
    """
    await _get_authorized_deployment(deployment_id, current_user.id, db)

    snapshot = models.TelemetrySnapshot(
        deployment_id=deployment_id,
        timestamp=payload.timestamp,
        health_status=payload.health_status,
        request_count=payload.request_count,
        error_count=payload.error_count,
        error_rate=payload.error_rate,
        latency_avg=payload.latency_avg,
        latency_p95=payload.latency_p95
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


@app.get(
    "/deployments/{deployment_id}/drift",
    response_model=List[schemas.DriftEventResponse]
)
async def list_deployment_drift(
    deployment_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List drift events recorded for an authorized deployment.
    """
    await _get_authorized_deployment(deployment_id, current_user.id, db)

    stmt = (
        select(models.DriftEvent)
        .filter(models.DriftEvent.deployment_id == deployment_id)
        .order_by(models.DriftEvent.detected_at.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()


@app.post(
    "/deployments/{deployment_id}/drift",
    response_model=schemas.DriftEventResponse,
    status_code=status.HTTP_201_CREATED
)
async def record_drift_event(
    deployment_id: UUID,
    payload: schemas.DriftEventCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Record a detected drift event for an authorized deployment.
    """
    await _get_authorized_deployment(deployment_id, current_user.id, db)

    event = models.DriftEvent(
        deployment_id=deployment_id,
        drift_type=payload.drift_type,
        expected_value=payload.expected_value,
        actual_value=payload.actual_value,
        severity=payload.severity,
        description=payload.description,
        detected_at=payload.detected_at,
        resolved_at=payload.resolved_at
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@app.get(
    "/deployments/{deployment_id}/rollbacks",
    response_model=List[schemas.RollbackRecordResponse]
)
async def list_deployment_rollbacks(
    deployment_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List rollback operations recorded for an authorized deployment.
    """
    await _get_authorized_deployment(deployment_id, current_user.id, db)

    stmt = (
        select(models.RollbackRecord)
        .filter(models.RollbackRecord.deployment_id == deployment_id)
        .order_by(models.RollbackRecord.created_at.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()


@app.post(
    "/deployments/{deployment_id}/rollbacks",
    response_model=schemas.RollbackRecordResponse,
    status_code=status.HTTP_201_CREATED
)
async def record_rollback(
    deployment_id: UUID,
    payload: schemas.RollbackRecordCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Record a rollback operation for an authorized deployment.
    """
    deployment = await _get_authorized_deployment(deployment_id, current_user.id, db)

    # If target_deployment_id is provided, verify it belongs to the same project
    if payload.target_deployment_id:
        target_stmt = select(models.Deployment).filter(
            models.Deployment.id == payload.target_deployment_id,
            models.Deployment.project_id == deployment.project_id
        )
        target_res = await db.execute(target_stmt)
        if not target_res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_deployment_id must belong to the same project"
            )

    record = models.RollbackRecord(
        deployment_id=deployment_id,
        target_deployment_id=payload.target_deployment_id,
        reason=payload.reason,
        trigger_source=payload.trigger_source,
        status=payload.status,
        safety_check_result=payload.safety_check_result,
        started_at=payload.started_at,
        completed_at=payload.completed_at,
        error_message=payload.error_message
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record

