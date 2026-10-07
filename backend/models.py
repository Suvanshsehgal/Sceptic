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
)
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
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


class PullRequest(Base):
    """
    Represents a Pull Request identified by repository and PR number.
    """
    __tablename__ = "pull_requests"

    id = Column(GUID(), primary_key=True, default=generate_uuid, index=True)
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

    # 1-to-many relationship with AuditRun (cascade deletion)
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
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship
    audit_run = relationship("AuditRun", back_populates="findings")

    __table_args__ = (
        Index("ix_agent_findings_audit_agent", "audit_run_id", "agent_name"),
    )
