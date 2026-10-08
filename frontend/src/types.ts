export interface User {
  id: string;
  name: string;
  email: string;
  avatar_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  user_id: string;
  name: string;
  repository_url?: string | null;
  default_branch?: string | null;
  description?: string | null;
  created_at: string;
  updated_at: string;
}

export interface FeatureAnalysis {
  id: string;
  project_id: string;
  user_id: string;
  feature_description: string;
  feasibility_score: number;
  complexity_score: number;
  risk_score: number;
  confidence_score: number;
  analysis: string;
  implementation_plan: string;
  created_at: string;
}

export interface AgentFinding {
  id: string;
  agent_name: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO' | string;
  status: 'OPEN' | 'VALID' | 'INVALID' | 'UNRESOLVED' | string;
  title: string;
  description: string;
  file_path?: string | null;
  line_number?: number | null;
  evidence?: any;
  recommendation?: string | null;
  language?: string | null;
  created_at: string;
}

export interface PullRequestSummary {
  id: string;
  repository: string;
  pr_number: number;
  latest_commit_sha?: string | null;
  title?: string | null;
  project_id?: string | null;
}

export interface AuditRun {
  id: string;
  pull_request_id: string;
  commit_sha: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | string;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  trust_score?: number | null;
  summary?: string | null;
  recommendation?: 'APPROVE' | 'REQUEST_CHANGES' | 'BLOCK' | string | null;
  idempotency_key: string;
  findings: AgentFinding[];
  pull_request?: PullRequestSummary | null;
}

export interface BackendHealth {
  status: string;
  database?: number;
  message?: string;
}

export interface TelemetrySnapshot {
  id: string;
  deployment_id: string;
  timestamp: string;
  health_status: string;
  request_count?: number | null;
  error_count?: number | null;
  error_rate?: number | null;
  latency_avg?: number | null;
  latency_p95?: number | null;
}

export interface DriftEvent {
  id: string;
  deployment_id: string;
  drift_type: string;
  expected_value: string;
  actual_value: string;
  severity: string;
  description: string;
  detected_at: string;
  resolved_at?: string | null;
}
