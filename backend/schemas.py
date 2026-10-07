from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class AgentFindingBase(BaseModel):
    agent_name: str
    severity: str
    title: str
    description: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    evidence: Optional[str] = None

class AgentFindingResponse(AgentFindingBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class AuditRunBase(BaseModel):
    status: str
    trust_score: Optional[int] = None
    summary: Optional[str] = None
    recommendation: Optional[str] = None
    
class PullRequestSummary(BaseModel):
    id: int
    repository_full_name: str
    pr_number: int
    commit_sha: str
    branch_name: Optional[str] = None

    class Config:
        from_attributes = True

class AuditRunResponse(AuditRunBase):
    id: int
    pull_request_id: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    findings: List[AgentFindingResponse] = []
    pull_request: Optional[PullRequestSummary] = None

    class Config:
        from_attributes = True

class PullRequestBase(BaseModel):
    repository_full_name: str
    pr_number: int
    commit_sha: str
    branch_name: Optional[str] = None

class PullRequestResponse(PullRequestBase):
    id: int
    created_at: datetime
    audit_runs: List[AuditRunResponse] = []

    class Config:
        from_attributes = True
