import {
  AuditRun,
  BackendHealth,
  Deployment,
  DriftEvent,
  LiveMetrics,
  Project,
  RollbackExecution,
  RollbackRecord,
  RollbackRequest,
  RollbackSafetyEvaluation,
  TelemetrySnapshot,
  WatchdogResult,
} from './types';

const API_BASE = '/api';

function authHeaders(): HeadersInit {
  try {
    const token = localStorage.getItem('sceptic_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export async function fetchHealth(): Promise<BackendHealth> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) {
    throw new Error(`Failed to fetch health status (${res.status})`);
  }
  return res.json();
}

export async function fetchAudits(skip = 0, limit = 100): Promise<AuditRun[]> {
  const res = await fetch(`${API_BASE}/audits?skip=${skip}&limit=${limit}`, { headers: authHeaders() });
  if (res.status === 401) {
    throw new Error('Sign in to view audits.');
  }
  if (!res.ok) {
    throw new Error(`Failed to fetch audits (${res.status})`);
  }
  return res.json();
}

export async function fetchAuditById(id: number | string): Promise<AuditRun> {
  const res = await fetch(`${API_BASE}/audits/${id}`, { headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`Failed to fetch audit #${id} (${res.status})`);
  }
  return res.json();
}

function jsonHeaders(): HeadersInit {
  return { 'Content-Type': 'application/json', ...authHeaders() };
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`GET ${path} failed (${res.status}): ${body.slice(0, 200)}`);
  }
  return res.json();
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`POST ${path} failed (${res.status}): ${detail.slice(0, 200)}`);
  }
  return res.json();
}

export function fetchProjects(): Promise<Project[]> {
  return getJson<Project[]>('/projects');
}

export function fetchDeployments(projectId: string): Promise<Deployment[]> {
  return getJson<Deployment[]>(`/projects/${projectId}/deployments`);
}

export function fetchLiveMetrics(deploymentId: string): Promise<LiveMetrics> {
  return getJson<LiveMetrics>(`/deployments/${deploymentId}/live`);
}

export function fetchTelemetry(deploymentId: string): Promise<TelemetrySnapshot[]> {
  return getJson<TelemetrySnapshot[]>(`/deployments/${deploymentId}/telemetry`);
}

export function fetchDriftEvents(deploymentId: string): Promise<DriftEvent[]> {
  return getJson<DriftEvent[]>(`/deployments/${deploymentId}/drift-events`);
}

export function fetchRollbacks(deploymentId: string): Promise<RollbackRecord[]> {
  return getJson<RollbackRecord[]>(`/deployments/${deploymentId}/rollbacks`);
}

export function runWatchdogCheck(deploymentId: string): Promise<WatchdogResult> {
  return postJson<WatchdogResult>(`/deployments/${deploymentId}/watchdog/check`);
}

export function checkRollbackSafety(deploymentId: string, body: RollbackRequest): Promise<RollbackSafetyEvaluation> {
  return postJson<RollbackSafetyEvaluation>(`/deployments/${deploymentId}/rollback/check`, body);
}

export function executeRollback(deploymentId: string, body: RollbackRequest): Promise<RollbackExecution> {
  return postJson<RollbackExecution>(`/deployments/${deploymentId}/rollback`, body);
}

export function auditStreamUrl(auditId: number | string, token: string | null): string {
  const query = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${API_BASE}/audits/${auditId}/stream${query}`;
}
