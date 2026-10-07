import { AuditRun, BackendHealth } from './types';

const API_BASE = '/api';

export async function fetchHealth(): Promise<BackendHealth> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) {
    throw new Error(`Failed to fetch health status (${res.status})`);
  }
  return res.json();
}

export async function fetchAudits(skip = 0, limit = 100): Promise<AuditRun[]> {
  const res = await fetch(`${API_BASE}/audits?skip=${skip}&limit=${limit}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch audits (${res.status})`);
  }
  return res.json();
}

export async function fetchAuditById(id: number | string): Promise<AuditRun> {
  const res = await fetch(`${API_BASE}/audits/${id}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch audit #${id} (${res.status})`);
  }
  return res.json();
}
