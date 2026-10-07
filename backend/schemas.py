from datetime import datetime, timezone
from enum import Enum
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


# ==========================================
# DEPLOYMENT SCHEMAS (PHASE 10)
# ==========================================

class DeploymentStatus(str, Enum):
    PENDING = "PENDING"
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class DeploymentBase(BaseModel):
    commit_sha: str = Field(..., min_length=1, max_length=100)
    image_name: str = Field(..., min_length=1, max_length=255)
    image_tag: str = Field(..., min_length=1, max_length=100)
    image_digest: Optional[str] = Field(None, max_length=255)
    environment: str = Field("production", min_length=1, max_length=50)
    version: Optional[str] = Field(None, max_length=100)
    status: DeploymentStatus = DeploymentStatus.PENDING
    deployed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    previous_deployment_id: Optional[UUID] = None


class DeploymentCreate(DeploymentBase):
    pass


class DeploymentStatusUpdate(BaseModel):
    status: DeploymentStatus
    deployed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DeploymentResponse(DeploymentBase):
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# TELEMETRY SNAPSHOT SCHEMAS
# ==========================================

class TelemetrySnapshotBase(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    health_status: str = Field("healthy", min_length=1, max_length=50)
    request_count: Optional[int] = Field(None, ge=0)
    error_count: Optional[int] = Field(None, ge=0)
    error_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    latency_avg: Optional[float] = Field(None, ge=0.0)
    latency_p95: Optional[float] = Field(None, ge=0.0)


class TelemetrySnapshotCreate(TelemetrySnapshotBase):
    pass


class TelemetrySnapshotResponse(TelemetrySnapshotBase):
    id: UUID
    deployment_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# DRIFT EVENT SCHEMAS
# ==========================================

class DriftType(str, Enum):
    COMMIT = "COMMIT"
    IMAGE = "IMAGE"
    IMAGE_DIGEST = "IMAGE_DIGEST"
    CONFIGURATION = "CONFIGURATION"
    ENVIRONMENT = "ENVIRONMENT"


class DriftEventBase(BaseModel):
    drift_type: str = Field(..., min_length=1, max_length=50)
    expected_value: str
    actual_value: str
    severity: str = Field("MEDIUM", max_length=50)
    description: str = Field(..., min_length=1)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None


class DriftEventCreate(DriftEventBase):
    pass


class DriftEventResponse(DriftEventBase):
    id: UUID
    deployment_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# ROLLBACK RECORD SCHEMAS
# ==========================================

class RollbackRecordBase(BaseModel):
    target_deployment_id: Optional[UUID] = None
    reason: str = Field(..., min_length=1)
    trigger_source: str = Field("MANUAL", max_length=100)
    status: str = Field("PENDING", max_length=50)
    safety_check_result: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class RollbackRecordCreate(RollbackRecordBase):
    pass


class RollbackRecordResponse(RollbackRecordBase):
    id: UUID
    deployment_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

