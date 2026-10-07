from datetime import datetime
from typing import List, Optional, Any, Dict
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


# ==========================================
# USER & AUTH SCHEMAS
# ==========================================

class UserBase(BaseModel):
    name: str
    email: str
    avatar_url: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserRegister(BaseModel):
    name: str
    email: str
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    email: str
    password: str


class UserResponse(UserBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthAccountResponse(BaseModel):
    id: UUID
    user_id: UUID
    provider: str
    provider_account_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ==========================================
# PROJECT SCHEMAS
# ==========================================

class ProjectBase(BaseModel):
    name: str
    repository_url: Optional[str] = None
    default_branch: Optional[str] = "main"
    description: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectResponse(ProjectBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# FEATURE ANALYSIS SCHEMAS
# ==========================================

class FeatureAnalysisBase(BaseModel):
    feature_description: str


class FeatureAnalysisCreate(FeatureAnalysisBase):
    pass


class FeatureAnalysisResponse(FeatureAnalysisBase):
    id: UUID
    project_id: UUID
    user_id: UUID
    feasibility_score: float
    complexity_score: float
    risk_score: float
    confidence_score: float
    analysis: str
    implementation_plan: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# AGENT FINDING SCHEMAS
# ==========================================

class AgentFindingBase(BaseModel):
    agent_name: str
    severity: str = "INFO"
    status: str = "OPEN"
    title: str
    description: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    evidence: Optional[Dict[str, Any]] = None
    recommendation: Optional[str] = None
    language: Optional[str] = None


class AgentFindingCreate(AgentFindingBase):
    audit_run_id: UUID


class AgentFindingResponse(AgentFindingBase):
    id: UUID
    audit_run_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# PULL REQUEST SCHEMAS
# ==========================================

class PullRequestBase(BaseModel):
    repository: str
    pr_number: int
    title: Optional[str] = None
    description: Optional[str] = None
    source_branch: Optional[str] = None
    target_branch: Optional[str] = None
    author: Optional[str] = None
    latest_commit_sha: Optional[str] = None
    project_id: Optional[UUID] = None


class PullRequestCreate(PullRequestBase):
    pass


class PullRequestSummary(BaseModel):
    id: UUID
    repository: str
    pr_number: int
    latest_commit_sha: Optional[str] = None
    title: Optional[str] = None
    project_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# AUDIT RUN SCHEMAS
# ==========================================

class AuditRunBase(BaseModel):
    commit_sha: str
    status: str = "QUEUED"
    trust_score: Optional[float] = None
    summary: Optional[str] = None
    recommendation: Optional[str] = None
    error_message: Optional[str] = None
    idempotency_key: str


class AuditRunCreate(AuditRunBase):
    pull_request_id: UUID


class AuditRunResponse(AuditRunBase):
    id: UUID
    pull_request_id: UUID
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    pull_request: Optional[PullRequestSummary] = None
    findings: List[AgentFindingResponse] = []

    model_config = ConfigDict(from_attributes=True)


class PullRequestResponse(PullRequestBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    audit_runs: List[AuditRunResponse] = []

    model_config = ConfigDict(from_attributes=True)


class CLIAuditSubmission(BaseModel):
    target_path: str
    trust_score: float
    summary: Optional[str] = None
    recommendation: Optional[str] = "UNKNOWN"
    commit_sha: Optional[str] = "cli-local"
    findings: List[Dict[str, Any]] = []
