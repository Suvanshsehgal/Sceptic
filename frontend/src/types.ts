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
  database_status?: string;
  redis_configured?: boolean;
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

export interface Deployment {
  id: string;
  project_id: string;
  commit_sha: string;
  image_name: string;
  image_tag: string;
  image_digest?: string | null;
  environment: string;
  version?: string | null;
  status: 'PENDING' | 'DEPLOYING' | 'ACTIVE' | 'FAILED' | 'ROLLED_BACK' | string;
  deployed_at?: string | null;
  completed_at?: string | null;
  previous_deployment_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface LiveFinding {
  finding_type: string;
  severity: string;
  description: string;
}

export interface LiveMetrics {
  observed_at: string;
  health_status: string;
  request_count: number | null;
  error_count: number | null;
  error_rate: number | null;
  latency_avg: number | null;
  latency_p95: number | null;
  findings: LiveFinding[];
}

export interface RollbackRecord {
  id: string;
  deployment_id: string;
  target_deployment_id?: string | null;
  reason: string;
  trigger_source: string;
  status: 'PENDING' | 'IN_PROGRESS' | 'SUCCESS' | 'ABORTED' | 'FAILED' | string;
  safety_check_result?: Record<string, SafetyCheck> | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  created_at: string;
}

export interface SafetyCheck {
  passed: boolean;
  detail: string;
}

export interface RollbackSafetyEvaluation {
  deployment_id: string;
  target_deployment_id?: string | null;
  target_commit_sha?: string | null;
  target_image?: string | null;
  is_safe: boolean;
  safety_checks: Record<string, SafetyCheck>;
  message: string;
}

export interface RollbackExecution {
  rollback_record: RollbackRecord;
  status: string;
  success: boolean;
  message: string;
  safety_checks: Record<string, SafetyCheck>;
}

export interface WatchdogResult {
  status: string;
  summary: string;
  findings: LiveFinding[];
}

export interface AuditProgress {
  stage: string;
  agents: Record<string, { status: string; findings: number }>;
  updated_at?: string;
}

export interface RollbackRequest {
  reason: string;
  trigger_source?: string;
  target_deployment_id?: string | null;
  allow_unsafe_migration?: boolean;
}
