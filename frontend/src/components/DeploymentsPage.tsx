import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, AlertTriangle, CheckCircle2, RotateCcw, ShieldCheck } from 'lucide-react';
import {
  checkRollbackSafety,
  executeRollback,
  fetchDeployments,
  fetchDriftEvents,
  fetchLiveMetrics,
  fetchProjects,
  fetchRollbacks,
  fetchTelemetry,
  runWatchdogCheck,
} from '../api';
import { Deployment, RollbackSafetyEvaluation } from '../types';

const ERROR_RATE_LIMIT = 0.05; // matches WATCHDOG_ERROR_RATE_THRESHOLD default
const P95_LIMIT_SECONDS = 0.5; // matches WATCHDOG_LATENCY_P95_THRESHOLD default
const MIN_REASON_LENGTH = 3; // matches RollbackTriggerRequest.reason

const STATUS_STYLE: Record<string, string> = {
  ACTIVE: 'bg-accent/10 text-accent border-accent/30',
  DEPLOYING: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  PENDING: 'bg-surface-raised text-ink border-line-strong',
  FAILED: 'bg-danger/10 text-danger border-red-500/20',
  ROLLED_BACK: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
};

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? 'n/a' : `${(value * 100).toFixed(2)}%`;
}

function seconds(value: number | null | undefined): string {
  return value === null || value === undefined ? 'n/a' : `${value.toFixed(3)}s`;
}

function Sparkline({ values, limit, color }: { values: number[]; limit?: number; color: string }) {
  if (values.length < 2) {
    return <div className="h-16 flex items-center justify-center text-[11px] text-ink-subtle">Not enough snapshots yet</div>;
  }
  const max = Math.max(limit ?? 0, ...values, 1e-9);
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * 100},${100 - (v / max) * 100}`)
    .join(' ');
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-16 w-full">
      {limit !== undefined && (
        <line x1="0" x2="100" y1={100 - (limit / max) * 100} y2={100 - (limit / max) * 100} stroke="#f87171" strokeDasharray="2 2" strokeWidth="0.5" />
      )}
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={points} />
    </svg>
  );
}

export const DeploymentsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState<string>('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [targetId, setTargetId] = useState('');
  const [dryRun, setDryRun] = useState<RollbackSafetyEvaluation | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [watchdogMessage, setWatchdogMessage] = useState<string | null>(null);

  const { data: projects = [] } = useQuery({ queryKey: ['projects'], queryFn: fetchProjects });
  const activeProjectId = projectId || (projects.length > 0 ? projects[0].id : '');

  const { data: deployments = [], isLoading: loadingDeployments, error: deploymentsError } = useQuery<Deployment[]>({
    queryKey: ['deployments', activeProjectId],
    queryFn: () => fetchDeployments(activeProjectId),
    enabled: !!activeProjectId,
    refetchInterval: 10000,
  });

  const selected = useMemo(
    () => deployments.find((d) => d.id === selectedId) ?? deployments[0] ?? null,
    [deployments, selectedId]
  );
  const deploymentId = selected?.id ?? '';

  // Live numbers are read from the target and Prometheus on every poll and are not stored.
  const live = useQuery({
    queryKey: ['live', deploymentId],
    queryFn: () => fetchLiveMetrics(deploymentId),
    enabled: !!deploymentId,
    refetchInterval: 5000,
    retry: false,
  });

  const telemetry = useQuery({
    queryKey: ['telemetry', deploymentId],
    queryFn: () => fetchTelemetry(deploymentId),
    enabled: !!deploymentId,
    refetchInterval: 15000,
  });

  const drift = useQuery({
    queryKey: ['drift', deploymentId],
    queryFn: () => fetchDriftEvents(deploymentId),
    enabled: !!deploymentId,
    refetchInterval: 15000,
  });

  const rollbacks = useQuery({
    queryKey: ['rollbacks', deploymentId],
    queryFn: () => fetchRollbacks(deploymentId),
    enabled: !!deploymentId,
    refetchInterval: 15000,
  });

  const watchdog = useMutation({
    mutationFn: () => runWatchdogCheck(deploymentId),
    onSuccess: (result) => {
      setWatchdogMessage(`Watchdog: ${result.status}. ${result.summary}`);
      queryClient.invalidateQueries({ queryKey: ['telemetry', deploymentId] });
    },
    onError: (err: Error) => setWatchdogMessage(err.message),
  });

  const body = { reason: reason.trim(), trigger_source: 'MANUAL', target_deployment_id: targetId.trim() || null };

  const safetyCheck = useMutation({
    mutationFn: () => checkRollbackSafety(deploymentId, body),
    onSuccess: (result) => {
      setDryRun(result);
      setConfirmed(false);
    },
  });

  const rollback = useMutation({
    mutationFn: () => executeRollback(deploymentId, body),
    onSuccess: () => {
      setDryRun(null);
      setConfirmed(false);
      setReason('');
      queryClient.invalidateQueries({ queryKey: ['deployments', activeProjectId] });
      queryClient.invalidateQueries({ queryKey: ['rollbacks', deploymentId] });
    },
  });

  const reasonValid = reason.trim().length >= MIN_REASON_LENGTH;
  const canRollback = !!dryRun && dryRun.is_safe && confirmed && reasonValid && !rollback.isPending;

  const telemetryRows = telemetry.data ?? [];
  const errorSeries = [...telemetryRows].reverse().map((t) => t.error_rate ?? 0);
  const p95Series = [...telemetryRows].reverse().map((t) => t.latency_p95 ?? 0);
  const liveData = live.data;
  const errorBreach = liveData?.error_rate !== null && liveData?.error_rate !== undefined && liveData.error_rate > ERROR_RATE_LIMIT;
  const p95Breach = liveData?.latency_p95 !== null && liveData?.latency_p95 !== undefined && liveData.latency_p95 > P95_LIMIT_SECONDS;

  if (projects.length === 0) {
    return (
      <div className="rounded-xl border border-line bg-surface p-12 text-center text-sm text-ink-muted">
        Create a project first. Deployments are registered against a project.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <p className="text-xs text-ink-muted">
          Live values refresh every 5 seconds from the running service. Rollbacks need a passing safety check and an explicit confirmation.
        </p>
        <select
          value={activeProjectId}
          onChange={(e) => {
            setProjectId(e.target.value);
            setSelectedId(null);
            setDryRun(null);
          }}
          className="bg-surface border border-line rounded-lg px-3 py-1.5 text-xs text-ink outline-none focus:border-accent"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Deployment history */}
        <div className="xl:col-span-1 rounded-xl border border-line bg-surface overflow-hidden">
          <div className="p-4 border-b border-line text-xs font-semibold uppercase tracking-wider text-ink">Deployment history</div>
          {loadingDeployments ? (
            <div className="p-6 text-xs text-ink-muted animate-pulse">Loading deployments...</div>
          ) : deploymentsError ? (
            <div className="p-6 text-xs text-danger">{(deploymentsError as Error).message}</div>
          ) : deployments.length === 0 ? (
            <div className="p-6 text-xs text-ink-muted">No deployments recorded for this project.</div>
          ) : (
            <ul className="divide-y divide-line max-h-[420px] overflow-y-auto">
              {deployments.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => {
                      setSelectedId(d.id);
                      setDryRun(null);
                      setConfirmed(false);
                      setWatchdogMessage(null);
                    }}
                    className={`w-full text-left p-4 hover:bg-surface-raised/60 ${selected?.id === d.id ? 'bg-surface-raised/60' : ''}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-ink">{d.commit_sha.slice(0, 12)}</span>
                      <span className={`px-2 py-0.5 rounded border text-[10px] font-semibold uppercase ${STATUS_STYLE[d.status] ?? STATUS_STYLE.PENDING}`}>
                        {d.status}
                      </span>
                    </div>
                    <div className="mt-1 text-[11px] text-ink-muted font-mono">
                      {d.environment} · {d.version ?? 'no version'} · {new Date(d.created_at).toLocaleString()}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Selected deployment */}
        <div className="xl:col-span-2 space-y-6">
          {!selected ? (
            <div className="rounded-xl border border-line bg-surface p-12 text-center text-sm text-ink-muted">
              Select a deployment to see its live health.
            </div>
          ) : (
            <>
              {/* Live health */}
              <div className="rounded-xl border border-line bg-surface p-5 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-bold text-ink flex items-center gap-2">
                      <Activity className="h-4 w-4 text-accent" /> Live health
                    </h3>
                    <p className="text-[11px] text-ink-muted font-mono">
                      {selected.commit_sha.slice(0, 12)} · {selected.image_name}:{selected.image_tag}
                    </p>
                  </div>
                  <button
                    onClick={() => watchdog.mutate()}
                    disabled={watchdog.isPending}
                    className="px-3 py-1.5 rounded-lg border border-line-strong text-xs text-ink hover:bg-surface-raised disabled:opacity-50"
                  >
                    {watchdog.isPending ? 'Checking...' : 'Record Watchdog snapshot'}
                  </button>
                </div>

                {live.isError ? (
                  <div className="text-xs text-danger">Live metrics unavailable: {(live.error as Error).message}</div>
                ) : (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="p-3 rounded-lg bg-canvas border border-line">
                      <div className="text-[10px] uppercase text-ink-muted">Health</div>
                      <div className={`text-lg font-bold ${liveData?.health_status === 'healthy' ? 'text-accent' : 'text-danger'}`}>
                        {liveData?.health_status ?? '...'}
                      </div>
                    </div>
                    <div className="p-3 rounded-lg bg-canvas border border-line">
                      <div className="text-[10px] uppercase text-ink-muted">Error rate</div>
                      <div className={`text-lg font-bold ${errorBreach ? 'text-danger' : 'text-ink'}`}>{percent(liveData?.error_rate)}</div>
                    </div>
                    <div className="p-3 rounded-lg bg-canvas border border-line">
                      <div className="text-[10px] uppercase text-ink-muted">P95 latency</div>
                      <div className={`text-lg font-bold ${p95Breach ? 'text-warning' : 'text-ink'}`}>{seconds(liveData?.latency_p95)}</div>
                    </div>
                    <div className="p-3 rounded-lg bg-canvas border border-line">
                      <div className="text-[10px] uppercase text-ink-muted">Requests</div>
                      <div className="text-lg font-bold text-ink">{liveData?.request_count ?? 'n/a'}</div>
                    </div>
                  </div>
                )}

                {liveData && liveData.findings.length > 0 && (
                  <ul className="space-y-1 text-xs">
                    {liveData.findings.map((f, i) => (
                      <li key={`${f.finding_type}-${i}`} className="flex items-start gap-2 text-ink">
                        <AlertTriangle className="h-3.5 w-3.5 text-warning shrink-0 mt-0.5" />
                        <span><span className="font-mono text-ink">{f.finding_type}</span> — {f.description}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {watchdogMessage && <p className="text-xs text-ink">{watchdogMessage}</p>}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                  <div>
                    <div className="text-[11px] text-ink-muted mb-1">Error rate (recorded snapshots, limit {percent(ERROR_RATE_LIMIT)})</div>
                    <Sparkline values={errorSeries} limit={ERROR_RATE_LIMIT} color="#34d399" />
                  </div>
                  <div>
                    <div className="text-[11px] text-ink-muted mb-1">P95 latency (recorded snapshots, limit {P95_LIMIT_SECONDS}s)</div>
                    <Sparkline values={p95Series} limit={P95_LIMIT_SECONDS} color="#fbbf24" />
                  </div>
                </div>
              </div>

              {/* Drift events */}
              <div className="rounded-xl border border-line bg-surface overflow-hidden">
                <div className="p-4 border-b border-line text-xs font-semibold uppercase tracking-wider text-ink flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-cyan" /> Drift events
                </div>
                {drift.data && drift.data.length > 0 ? (
                  <table className="w-full text-left text-xs">
                    <thead className="bg-canvas text-ink-muted">
                      <tr>
                        <th className="py-2 px-4">Type</th>
                        <th className="py-2 px-4">Expected</th>
                        <th className="py-2 px-4">Actual</th>
                        <th className="py-2 px-4">Severity</th>
                        <th className="py-2 px-4">State</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line font-mono text-ink">
                      {drift.data.map((e) => (
                        <tr key={e.id}>
                          <td className="py-2 px-4">{e.drift_type}</td>
                          <td className="py-2 px-4 truncate max-w-[160px]">{e.expected_value}</td>
                          <td className="py-2 px-4 truncate max-w-[160px]">{e.actual_value}</td>
                          <td className="py-2 px-4">{e.severity}</td>
                          <td className="py-2 px-4">{e.resolved_at ? 'resolved' : 'open'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="p-6 text-xs text-ink-muted">No drift recorded. Run the Gatekeeper to check the running version.</div>
                )}
              </div>

              {/* Rollback */}
              <div className="rounded-xl border border-red-900/40 bg-surface p-5 space-y-4">
                <h3 className="text-sm font-bold text-ink flex items-center gap-2">
                  <RotateCcw className="h-4 w-4 text-danger" /> Roll back this deployment
                </h3>
                <p className="text-xs text-ink-muted">
                  Step 1 runs the safety checks without changing anything. Step 2 is enabled only when the checks pass and you confirm.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <textarea
                    value={reason}
                    onChange={(e) => {
                      setReason(e.target.value);
                      setDryRun(null);
                      setConfirmed(false);
                    }}
                    rows={2}
                    placeholder="Why roll back? (at least 3 characters)"
                    className="bg-canvas border border-line rounded-lg px-3 py-2 text-xs text-ink outline-none focus:border-accent"
                  />
                  <input
                    value={targetId}
                    onChange={(e) => {
                      setTargetId(e.target.value);
                      setDryRun(null);
                      setConfirmed(false);
                    }}
                    placeholder="Target deployment ID (optional, otherwise discovered)"
                    className="bg-canvas border border-line rounded-lg px-3 py-2 text-xs text-ink outline-none focus:border-accent font-mono"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => safetyCheck.mutate()}
                    disabled={!reasonValid || safetyCheck.isPending}
                    className="px-3 py-1.5 rounded-lg border border-line-strong text-xs text-ink hover:bg-surface-raised disabled:opacity-40"
                  >
                    {safetyCheck.isPending ? 'Checking...' : 'Step 1: run safety checks'}
                  </button>
                </div>

                {safetyCheck.isError && <p className="text-xs text-danger">{(safetyCheck.error as Error).message}</p>}

                {dryRun && (
                  <div className="space-y-3">
                    <div className={`text-xs font-semibold ${dryRun.is_safe ? 'text-accent' : 'text-danger'}`}>
                      {dryRun.is_safe ? <CheckCircle2 className="inline h-3.5 w-3.5 mr-1" /> : <AlertTriangle className="inline h-3.5 w-3.5 mr-1" />}
                      {dryRun.message}
                    </div>
                    <div className="text-[11px] text-ink-muted font-mono">
                      Target: {dryRun.target_deployment_id ?? 'none found'} {dryRun.target_commit_sha ? `(${dryRun.target_commit_sha.slice(0, 12)})` : ''}
                    </div>
                    <ul className="space-y-1 text-xs">
                      {Object.entries(dryRun.safety_checks).map(([name, check]) => (
                        <li key={name} className="flex gap-2">
                          <span className={check.passed ? 'text-accent' : 'text-danger'}>{check.passed ? 'PASS' : 'FAIL'}</span>
                          <span className="font-mono text-ink">{name}</span>
                          <span className="text-ink-muted">{check.detail}</span>
                        </li>
                      ))}
                    </ul>

                    {dryRun.is_safe && (
                      <div className="rounded-lg border border-red-900/50 bg-danger/10 p-3 space-y-2">
                        <label className="flex items-center gap-2 text-xs text-ink">
                          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                          I confirm rolling back {selected.commit_sha.slice(0, 12)} in {selected.environment}.
                        </label>
                        <button
                          onClick={() => rollback.mutate()}
                          disabled={!canRollback}
                          className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-ink text-xs font-semibold disabled:opacity-40"
                        >
                          {rollback.isPending ? 'Rolling back...' : 'Step 2: roll back now'}
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {rollback.data && (
                  <p className={`text-xs ${rollback.data.success ? 'text-accent' : 'text-danger'}`}>
                    Rollback {rollback.data.status}: {rollback.data.message}
                  </p>
                )}
                {rollback.isError && <p className="text-xs text-danger">{(rollback.error as Error).message}</p>}

                {/* History */}
                <div className="pt-2">
                  <div className="text-[11px] uppercase text-ink-muted mb-2">Rollback history</div>
                  {rollbacks.data && rollbacks.data.length > 0 ? (
                    <ul className="space-y-1 text-xs font-mono text-ink">
                      {rollbacks.data.map((r) => (
                        <li key={r.id}>
                          <span className="text-ink-muted">{new Date(r.created_at).toLocaleString()}</span> {r.status} · {r.trigger_source} · {r.reason}
                          {r.error_message ? <span className="text-danger"> · {r.error_message}</span> : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="text-xs text-ink-subtle">No rollbacks recorded.</div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
