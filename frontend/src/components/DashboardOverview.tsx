import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchAudits, fetchHealth } from '../api';
import { 
  FileCheck2, 
  CheckCircle2, 
  XCircle, 
  AlertTriangle, 
  ShieldAlert, 
  Clock, 
  TrendingUp,
  ArrowRight,
  Database,
  Radio
} from 'lucide-react';
import { AuditRun } from '../types';

interface DashboardOverviewProps {
  onSelectAudit: (id: number) => void;
  onNavigateTab: (tab: string) => void;
}

export const DashboardOverview: React.FC<DashboardOverviewProps> = ({
  onSelectAudit,
  onNavigateTab,
}) => {
  const { 
    data: audits, 
    isLoading: auditsLoading, 
    error: auditsError,
    refetch: refetchAudits 
  } = useQuery<AuditRun[]>({
    queryKey: ['audits'],
    queryFn: () => fetchAudits(0, 100),
    refetchInterval: 10000,
  });

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 15000,
  });

  if (auditsLoading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 bg-slate-800/60 rounded-xl border border-slate-700/50" />
          ))}
        </div>
        <div className="h-64 bg-slate-800/60 rounded-xl border border-slate-700/50" />
      </div>
    );
  }

  if (auditsError) {
    return (
      <div className="p-6 rounded-xl bg-red-950/30 border border-red-800/50 text-red-300">
        <div className="flex items-center gap-3 mb-2 font-semibold text-lg text-red-200">
          <AlertTriangle className="h-5 w-5 text-red-400" />
          <span>Failed to connect to Sceptic API</span>
        </div>
        <p className="text-sm text-red-400/90 mb-4">
          {(auditsError as Error).message || 'Unable to retrieve audit runs from backend.'}
        </p>
        <button
          onClick={() => refetchAudits()}
          className="px-4 py-2 rounded-lg bg-red-800/40 hover:bg-red-800/60 border border-red-700 text-sm font-medium text-white transition-colors"
        >
          Retry Connection
        </button>
      </div>
    );
  }

  const allAudits = audits || [];
  const totalAudits = allAudits.length;
  const completedAudits = allAudits.filter((a) => a.status === 'COMPLETED').length;
  const pendingOrRunning = allAudits.filter((a) => a.status === 'PENDING' || a.status === 'RUNNING').length;
  const failedAudits = allAudits.filter((a) => a.status === 'FAILED' || (a.status === 'COMPLETED' && a.recommendation === 'BLOCK')).length;

  // Calculate average trust score of completed audits
  const completedWithScore = allAudits.filter((a) => a.status === 'COMPLETED' && typeof a.trust_score === 'number');
  const avgTrustScore = completedWithScore.length > 0
    ? Math.round(completedWithScore.reduce((sum, a) => sum + (a.trust_score || 0), 0) / completedWithScore.length)
    : null;

  // Flatten findings across all runs for global breakdown
  const allFindings = allAudits.flatMap((a) => a.findings || []);
  const criticalFindings = allFindings.filter((f) => f.severity === 'CRITICAL').length;
  const highFindings = allFindings.filter((f) => f.severity === 'HIGH').length;
  const mediumFindings = allFindings.filter((f) => f.severity === 'MEDIUM').length;

  return (
    <div className="space-y-6">
      {/* Infrastructure Status Banner */}
      {health && (
        <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl bg-slate-900 border border-slate-800 text-xs">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-emerald-400" />
              <span className="text-slate-400">PostgreSQL:</span>
              <span className="font-mono text-slate-200">{health.database_status}</span>
            </div>
            <div className="flex items-center gap-2">
              <Radio className="h-4 w-4 text-emerald-400" />
              <span className="text-slate-400">Redis Celery:</span>
              <span className="font-mono text-slate-200">
                {health.redis_configured ? 'Active' : 'Unconfigured'}
              </span>
            </div>
          </div>
          <div className="text-slate-400 font-mono">
            {health.message}
          </div>
        </div>
      )}

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Audits */}
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Total Audits</span>
            <FileCheck2 className="h-4 w-4 text-slate-400" />
          </div>
          <div className="text-2xl font-bold text-white font-mono">{totalAudits}</div>
          <div className="text-xs text-slate-400 mt-1 flex items-center gap-1.5">
            <span className="text-slate-300 font-medium">{pendingOrRunning}</span> in progress
          </div>
        </div>

        {/* Average Trust Score */}
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Average Trust Score</span>
            <TrendingUp className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-bold font-mono ${
              avgTrustScore === null ? 'text-slate-400' :
              avgTrustScore >= 85 ? 'text-emerald-400' :
              avgTrustScore >= 65 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {avgTrustScore !== null ? avgTrustScore : 'N/A'}
            </span>
            {avgTrustScore !== null && <span className="text-xs text-slate-400">/ 100</span>}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            Across {completedWithScore.length} completed audits
          </div>
        </div>

        {/* Completed vs Blocked */}
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Verified Runs</span>
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-emerald-400 font-mono">{completedAudits}</div>
          <div className="text-xs text-red-400 mt-1">
            {failedAudits} blocked or failed
          </div>
        </div>

        {/* Critical & High Findings */}
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium uppercase tracking-wider">Security / Spec Issues</span>
            <ShieldAlert className="h-4 w-4 text-red-400" />
          </div>
          <div className="text-2xl font-bold text-red-400 font-mono">{criticalFindings + highFindings}</div>
          <div className="text-xs text-slate-400 mt-1">
            {criticalFindings} critical · {highFindings} high · {mediumFindings} medium
          </div>
        </div>
      </div>

      {/* Recent Audits Table Card */}
      <div className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden">
        <div className="p-5 border-b border-slate-800 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">Recent Audits</h2>
            <p className="text-xs text-slate-400 mt-0.5">Real-time status of verification runs from CLI and Webhooks</p>
          </div>
          <button
            onClick={() => onNavigateTab('audits')}
            className="flex items-center gap-1.5 text-xs text-emerald-400 hover:text-emerald-300 font-medium"
          >
            <span>View All</span>
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>

        {allAudits.length === 0 ? (
          <div className="p-12 text-center">
            <FileCheck2 className="h-10 w-10 text-slate-600 mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-slate-300">No Audits Recorded Yet</h3>
            <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
              Run <code className="bg-slate-800 px-1.5 py-0.5 rounded text-emerald-400 font-mono">sceptic audit &lt;path&gt;</code> in your terminal or trigger a webhook to record your first audit.
            </p>
            <button
              onClick={() => onNavigateTab('docs')}
              className="mt-4 px-4 py-2 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 text-xs font-semibold"
            >
              Read CLI Instructions
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Audit ID</th>
                  <th className="py-3 px-4">Repository / PR</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Trust Score</th>
                  <th className="py-3 px-4">Verdict</th>
                  <th className="py-3 px-4">Findings</th>
                  <th className="py-3 px-4">Timestamp</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300 font-mono">
                {allAudits.slice(0, 5).map((audit) => {
                  const pr = audit.pull_request;
                  const score = audit.trust_score;
                  return (
                    <tr 
                      key={audit.id} 
                      className="hover:bg-slate-800/30 transition-colors cursor-pointer"
                      onClick={() => onSelectAudit(audit.id)}
                    >
                      <td className="py-3 px-4 font-bold text-white">#{audit.id}</td>
                      <td className="py-3 px-4">
                        {pr ? (
                          <div className="font-sans">
                            <span className="font-medium text-slate-200">{pr.repository_full_name}</span>
                            <span className="text-slate-400 text-[11px] block font-mono">
                              PR #{pr.pr_number} ({pr.commit_sha.substring(0, 7)})
                            </span>
                          </div>
                        ) : (
                          <span className="text-slate-400 italic font-sans">CLI / In-Process Audit</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                          audit.status === 'COMPLETED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                          audit.status === 'RUNNING' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20 animate-pulse' :
                          audit.status === 'FAILED' ? 'bg-red-500/10 text-red-400 border border-red-500/20' :
                          'bg-slate-800 text-slate-400'
                        }`}>
                          {audit.status}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        {score !== null && score !== undefined ? (
                          <span className={`font-bold ${
                            score >= 85 ? 'text-emerald-400' :
                            score >= 65 ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {score} / 100
                          </span>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
                      <td className="py-3 px-4 font-sans font-medium">
                        {audit.recommendation ? (
                          <span className={`text-[11px] font-bold ${
                            audit.recommendation === 'APPROVE' ? 'text-emerald-400' :
                            audit.recommendation === 'REQUEST_CHANGES' ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {audit.recommendation}
                          </span>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                          {audit.findings?.length || 0}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-slate-400 font-sans text-[11px]">
                        {new Date(audit.started_at).toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectAudit(audit.id);
                          }}
                          className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-emerald-400 hover:text-emerald-300 font-sans text-xs transition-colors"
                        >
                          View Details
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
