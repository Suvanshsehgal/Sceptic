export interface AgentFinding {
  id: number;
  agent_name: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO' | string;
  title: string;
  description: string;
  file_path?: string | null;
  line_number?: number | null;
  evidence?: string | null;
  created_at: string;
}

export interface PullRequestSummary {
  id: number;
  repository_full_name: string;
  pr_number: number;
  commit_sha: string;
  branch_name?: string | null;
}

export interface AuditRun {
  id: number;
  pull_request_id: number;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | string;
  started_at: string;
  completed_at?: string | null;
  trust_score?: number | null;
  summary?: string | null;
  recommendation?: 'APPROVE' | 'REQUEST_CHANGES' | 'BLOCK' | string | null;
  findings: AgentFinding[];
  pull_request?: PullRequestSummary | null;
}

export interface BackendHealth {
  status: string;
  database_status: string;
  redis_configured: boolean;
  message: string;
}
