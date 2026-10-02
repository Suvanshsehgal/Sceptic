from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class PullRequest(Base):
    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True, index=True)
    repository_full_name = Column(String, index=True, nullable=False)
    pr_number = Column(Integer, index=True, nullable=False)
    commit_sha = Column(String, nullable=False)
    branch_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    audit_runs = relationship("AuditRun", back_populates="pull_request", cascade="all, delete-orphan")

class AuditRun(Base):
    __tablename__ = "audit_runs"

    id = Column(Integer, primary_key=True, index=True)
    pull_request_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    status = Column(String, default="PENDING", nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    pull_request = relationship("PullRequest", back_populates="audit_runs")
    findings = relationship("AgentFinding", back_populates="audit_run", cascade="all, delete-orphan")

class AgentFinding(Base):
    __tablename__ = "agent_findings"

    id = Column(Integer, primary_key=True, index=True)
    audit_run_id = Column(Integer, ForeignKey("audit_runs.id"), nullable=False)
    agent_name = Column(String, nullable=False)
    severity = Column(String, default="INFO", nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    file_path = Column(String, nullable=True)
    line_number = Column(Integer, nullable=True)
    evidence = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    audit_run = relationship("AuditRun", back_populates="findings")
