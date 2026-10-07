import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    JSON,
    CheckConstraint
)
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from database import Base


class GUID(TypeDecorator):
    """Platform-independent GUID/UUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing as stringified hex values.
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == "postgresql":
            return str(value) if not isinstance(value, uuid.UUID) else value
        else:
            if not isinstance(value, uuid.UUID):
                return str(uuid.UUID(str(value)))
            else:
                return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            return uuid.UUID(str(value))
        return value


def generate_uuid():
    return uuid.uuid4()


# ========================================================
# 1. USER & AUTHENTICATION MODELS
# ========================================================

class User(Base):
    """
    Sceptic User account representing an individual developer.
    """
    __tablename__ = "users"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=True)
    avatar_url = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    auth_accounts = relationship(
        "AuthAccount",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(AuthAccount.created_at)"
    )
    projects = relationship(
        "Project",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(Project.created_at)"
    )
    feature_analyses = relationship(
        "FeatureAnalysis",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(FeatureAnalysis.created_at)"
    )


class AuthAccount(Base):
    """
    Connects a Sceptic user to an external identity provider (Google, etc.).
    """
    __tablename__ = "auth_accounts"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    provider = Column(String(50), nullable=False, default="google", index=True)
    provider_account_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", back_populates="auth_accounts")

    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_auth_accounts_provider_account"),
    )


# ========================================================
# 2. PROJECTS & FEATURE ANALYSES
# ========================================================

class Project(Base):
    """
    A developer project repository owned by a User.
    """
    __tablename__ = "projects"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    name = Column(String(255), nullable=False, index=True)
    repository_url = Column(String(1000), nullable=True)
    default_branch = Column(String(100), nullable=True, default="main")
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="projects")
    pull_requests = relationship(
        "PullRequest",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(PullRequest.created_at)"
    )
    feature_analyses = relationship(
        "FeatureAnalysis",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(FeatureAnalysis.created_at)"
    )
    deployments = relationship(
        "Deployment",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(Deployment.created_at)"
    )

    __table_args__ = (
        Index("ix_projects_user_name", "user_id", "name"),
    )


class FeatureAnalysis(Base):
    """
    Architecture and implementation feasibility analysis for a new feature proposal.
    Generated via `sceptic newfeature` or Web UI.
    """
    __tablename__ = "feature_analyses"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    feature_description = Column(Text, nullable=False)
    feasibility_score = Column(Float, nullable=False)
    complexity_score = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False)
    analysis = Column(Text, nullable=False)
    implementation_plan = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    project = relationship("Project", back_populates="feature_analyses")
    user = relationship("User", back_populates="feature_analyses")

    __table_args__ = (
        CheckConstraint("feasibility_score >= 0 AND feasibility_score <= 100", name="chk_feature_feasibility_score"),
        CheckConstraint("complexity_score >= 0 AND complexity_score <= 100", name="chk_feature_complexity_score"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="chk_feature_risk_score"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="chk_feature_confidence_score"),
        Index("ix_feature_analyses_proj_user", "project_id", "user_id"),
    )


# ========================================================
# 3. EXISTING AUDIT & VERIFICATION MODELS (EXTENDED)
# ========================================================

class PullRequest(Base):
    """
    Represents a Pull Request identified by repository and PR number.
    Optionally belongs to a Project.
    """
    __tablename__ = "pull_requests"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    repository = Column(String(255), nullable=False, index=True)
    pr_number = Column(Integer, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    source_branch = Column(String(255), nullable=True)
    target_branch = Column(String(255), nullable=True)
    author = Column(String(255), nullable=True)
    latest_commit_sha = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    project = relationship("Project", back_populates="pull_requests")
    audit_runs = relationship(
        "AuditRun",
        back_populates="pull_request",
        cascade="all, delete-orphan",
        order_by="desc(AuditRun.created_at)",
    )

    # Constraints & Indexes
    __table_args__ = (
        UniqueConstraint("repository", "pr_number", name="uq_pull_requests_repository_pr_number"),
        Index("ix_pull_requests_repo_pr", "repository", "pr_number"),
    )


class AuditRun(Base):
    """
    Represents a single audit execution for a pull request and commit.
    """
    __tablename__ = "audit_runs"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    pull_request_id = Column(
        GUID(),
        ForeignKey("pull_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    commit_sha = Column(String(100), nullable=False, index=True)
    status = Column(String(50), default="QUEUED", nullable=False, index=True)
    trust_score = Column(Float, nullable=True)
    summary = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    idempotency_key = Column(String(255), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    pull_request = relationship("PullRequest", back_populates="audit_runs")
    findings = relationship(
        "AgentFinding",
        back_populates="audit_run",
        cascade="all, delete-orphan",
        order_by="desc(AgentFinding.created_at)",
    )

    __table_args__ = (
        Index("ix_audit_runs_pr_commit", "pull_request_id", "commit_sha"),
    )


class AgentFinding(Base):
    """
    Represents an individual ground-truth finding from a verification agent.
    """
    __tablename__ = "agent_findings"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    audit_run_id = Column(
        GUID(),
        ForeignKey("audit_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_name = Column(String(100), nullable=False, index=True)
    severity = Column(String(50), default="INFO", nullable=False, index=True)
    status = Column(String(50), default="OPEN", nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    file_path = Column(String(1000), nullable=True)
    line_number = Column(Integer, nullable=True)
    evidence = Column(JSON, nullable=True)
    recommendation = Column(Text, nullable=True)
    language = Column(String(50), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship
    audit_run = relationship("AuditRun", back_populates="findings")

    __table_args__ = (
        Index("ix_agent_findings_audit_agent", "audit_run_id", "agent_name"),
    )


# ========================================================
# 4. DEPLOYMENT & OBSERVABILITY STATE MODELS (PHASE 10)
# ========================================================

class Deployment(Base):
    """
    Represents a discrete application deployment for a Project repository.
    Serves as the root entity for post-deployment observability, drift detection, and recovery.
    """
    __tablename__ = "deployments"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    commit_sha = Column(String(100), nullable=False, index=True)
    image_name = Column(String(255), nullable=False)
    image_tag = Column(String(100), nullable=False)
    image_digest = Column(String(255), nullable=True)
    environment = Column(String(50), nullable=False, default="production", index=True)
    version = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="PENDING", index=True)
    deployed_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    previous_deployment_id = Column(
        GUID(),
        ForeignKey("deployments.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    project = relationship("Project", back_populates="deployments")
    previous_deployment = relationship(
        "Deployment",
        remote_side=[id],
        foreign_keys=[previous_deployment_id],
        backref="subsequent_deployments"
    )
    telemetry_snapshots = relationship(
        "TelemetrySnapshot",
        back_populates="deployment",
        cascade="all, delete-orphan",
        order_by="desc(TelemetrySnapshot.timestamp)"
    )
    drift_events = relationship(
        "DriftEvent",
        back_populates="deployment",
        cascade="all, delete-orphan",
        order_by="desc(DriftEvent.detected_at)"
    )
    rollback_records = relationship(
        "RollbackRecord",
        foreign_keys="[RollbackRecord.deployment_id]",
        back_populates="deployment",
        cascade="all, delete-orphan",
        order_by="desc(RollbackRecord.created_at)"
    )

    __table_args__ = (
        Index("ix_deployments_project_status", "project_id", "status"),
        Index("ix_deployments_project_env", "project_id", "environment"),
    )


class TelemetrySnapshot(Base):
    """
    Persists structured observations of deployed application health and performance.
    Consumed by the future Pipeline Watchdog agent.
    """
    __tablename__ = "telemetry_snapshots"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    deployment_id = Column(
        GUID(),
        ForeignKey("deployments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    health_status = Column(String(50), nullable=False, default="healthy")
    request_count = Column(Integer, nullable=True)
    error_count = Column(Integer, nullable=True)
    error_rate = Column(Float, nullable=True)
    latency_avg = Column(Float, nullable=True)
    latency_p95 = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    deployment = relationship("Deployment", back_populates="telemetry_snapshots")

    __table_args__ = (
        Index("ix_telemetry_deployment_timestamp", "deployment_id", "timestamp"),
        CheckConstraint("request_count IS NULL OR request_count >= 0", name="chk_telemetry_request_count"),
        CheckConstraint("error_count IS NULL OR error_count >= 0", name="chk_telemetry_error_count"),
        CheckConstraint("error_rate IS NULL OR (error_rate >= 0.0 AND error_rate <= 1.0)", name="chk_telemetry_error_rate"),
        CheckConstraint("latency_avg IS NULL OR latency_avg >= 0.0", name="chk_telemetry_latency_avg"),
        CheckConstraint("latency_p95 IS NULL OR latency_p95 >= 0.0", name="chk_telemetry_latency_p95"),
    )


class DriftEvent(Base):
    """
    Captures configuration, image, or environmental deviations between desired and observed state.
    Consumed by the future Gatekeeper agent.
    """
    __tablename__ = "drift_events"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    deployment_id = Column(
        GUID(),
        ForeignKey("deployments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    drift_type = Column(String(50), nullable=False, index=True)
    expected_value = Column(Text, nullable=False)
    actual_value = Column(Text, nullable=False)
    severity = Column(String(50), default="MEDIUM", nullable=False, index=True)
    description = Column(Text, nullable=False)
    detected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    deployment = relationship("Deployment", back_populates="drift_events")

    __table_args__ = (
        Index("ix_drift_events_deployment_detected", "deployment_id", "detected_at"),
    )


class RollbackRecord(Base):
    """
    Records recovery and rollback operations targeting a previous known-good deployment.
    Consumed by the future Rollback agent.
    """
    __tablename__ = "rollback_records"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
    deployment_id = Column(
        GUID(),
        ForeignKey("deployments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    target_deployment_id = Column(
        GUID(),
        ForeignKey("deployments.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    reason = Column(Text, nullable=False)
    trigger_source = Column(String(100), default="MANUAL", nullable=False)
    status = Column(String(50), default="PENDING", nullable=False, index=True)
    safety_check_result = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    deployment = relationship("Deployment", foreign_keys=[deployment_id], back_populates="rollback_records")
    target_deployment = relationship("Deployment", foreign_keys=[target_deployment_id])

    __table_args__ = (
        Index("ix_rollback_records_deployment_created", "deployment_id", "created_at"),
    )
