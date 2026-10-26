import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchAudits, fetchHealth } from '../api';
import { useAuth } from '../context/AuthContext';
import { ArrowRight, CheckCircle2, Database, FileCheck2, Radio, Rocket, ShieldAlert, TrendingUp } from 'lucide-react';
import { AuditRun } from '../types';
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  PageHeader,
  RecommendationBadge,
  Skeleton,
  StatCard,
  StatusBadge,
  Tone,
  tableClasses,
  trustTone,
} from './ui';

interface DashboardOverviewProps {
  onSelectAudit: (id: number | string) => void;
  onNavigateTab: (tab: string) => void;
}

function formatTime(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString();
}

export const DashboardOverview: React.FC<DashboardOverviewProps> = ({ onSelectAudit, onNavigateTab }) => {
  const { token } = useAuth();
  const {
    data: audits,
    isLoading: auditsLoading,
    error: auditsError,
    refetch: refetchAudits,
  } = useQuery<AuditRun[]>({
    queryKey: ['audits'],
    queryFn: () => fetchAudits(0, 100),
    refetchInterval: 10000,
    enabled: !!token,
  });

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 15000,
  });

  if (!token) {
    return (
      <div className="space-y-8">
        <PageHeader title="Overview" description="Sign in to see your verification runs, trust scores, and findings." />
        <Card>
          <EmptyState
            icon={<FileCheck2 className="h-9 w-9" />}
            title="You are not signed in"
            description="Audits from the CLI and from pull request webhooks appear here once you sign in. Service status is shown below."
            action={<Button variant="primary" onClick={() => onNavigateTab('docs')}>Read the setup guide</Button>}
          />
        </Card>
        <Card padded={false}>
          <dl className="grid grid-cols-1 divide-y divide-line text-[13px] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            <div className="flex items-center justify-between px-5 py-3.5">
              <dt className="text-ink-muted">Engine</dt>
              <dd className="font-mono text-ink">{health ? 'Online' : 'Unreachable'}</dd>
            </div>
            <div className="flex items-center justify-between px-5 py-3.5">
              <dt className="text-ink-muted">Database</dt>
              <dd className="font-mono text-ink">{health?.database_status ?? 'Unknown'}</dd>
            </div>
            <div className="flex items-center justify-between px-5 py-3.5">
              <dt className="text-ink-muted">Task queue</dt>
              <dd className="font-mono text-ink">{health?.redis_configured ? 'Active' : 'Not configured'}</dd>
            </div>
          </dl>
        </Card>
      </div>
    );
  }

  if (auditsLoading) {
    return (
      <div className="space-y-6" aria-busy="true" aria-label="Loading dashboard">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-72" />
      </div>
    );
  }

  if (auditsError) {
    return (
      <ErrorBanner
        title="Cannot reach the Sceptic API"
        message={(auditsError as Error).message || 'Unable to retrieve audit runs from the backend.'}
        action={<Button variant="secondary" size="sm" onClick={() => refetchAudits()}>Try again</Button>}
      />
    );
  }

  const allAudits = audits || [];
  const completed = allAudits.filter((a) => a.status === 'COMPLETED');
  const inProgress = allAudits.filter((a) => a.status === 'QUEUED' || a.status === 'PENDING' || a.status === 'RUNNING').length;
  const blockedOrFailed = allAudits.filter(
    (a) => a.status === 'FAILED' || (a.status === 'COMPLETED' && a.recommendation === 'BLOCK')
  ).length;

  const scored = completed.filter((a) => typeof a.trust_score === 'number');
  const averageScore = scored.length
    ? Math.round(scored.reduce((sum, a) => sum + (a.trust_score || 0), 0) / scored.length)
    : null;

  const allFindings = allAudits.flatMap((a) => a.findings || []);
  const critical = allFindings.filter((f) => f.severity === 'CRITICAL').length;
  const high = allFindings.filter((f) => f.severity === 'HIGH').length;
  const medium = allFindings.filter((f) => f.severity === 'MEDIUM').length;

  const engineOnline = !!health;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Overview"
        description="How recent code verification runs look, where the trust scores sit, and which findings need attention."
        actions={
          <Button variant="primary" onClick={() => onNavigateTab('audits')}>
            View all audits <ArrowRight className="h-4 w-4" aria-hidden />
          </Button>
        }
      />

      {/* Service status */}
      <Card padded={false}>
        <dl className="grid grid-cols-1 divide-y divide-line text-xs sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <div className="flex items-center gap-3 px-5 py-3">
            <Database className="h-4 w-4 text-ink-subtle" aria-hidden />
            <dt className="text-ink-muted">Database</dt>
            <dd className="ml-auto font-mono text-ink">{engineOnline ? health?.database_status ?? 'Connected' : 'Unknown'}</dd>
          </div>
          <div className="flex items-center gap-3 px-5 py-3">
            <Radio className="h-4 w-4 text-ink-subtle" aria-hidden />
            <dt className="text-ink-muted">Task queue</dt>
            <dd className="ml-auto font-mono text-ink">{health?.redis_configured ? 'Active' : 'Not configured'}</dd>
          </div>
          <div className="flex items-center gap-3 px-5 py-3">
            <Rocket className="h-4 w-4 text-ink-subtle" aria-hidden />
            <dt className="text-ink-muted">Post-deploy checks</dt>
            <dd className="ml-auto font-mono text-ink">Watchdog and Gatekeeper</dd>
          </div>
        </dl>
      </Card>

      {/* Key numbers */}
      <section aria-label="Key numbers" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Audits"
          value={allAudits.length}
          hint={`${inProgress} in progress`}
          icon={<FileCheck2 className="h-4 w-4" />}
        />
        <StatCard
          label="Average trust score"
          value={averageScore === null ? '-' : `${averageScore}/100`}
          tone={averageScore === null ? 'neutral' : (trustTone(averageScore) as Tone)}
          hint={scored.length ? `Across ${scored.length} completed audits` : 'No completed audits yet'}
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <StatCard
          label="Completed"
          value={completed.length}
          tone="success"
          hint={blockedOrFailed ? `${blockedOrFailed} blocked or failed` : 'None blocked or failed'}
          icon={<CheckCircle2 className="h-4 w-4" />}
        />
        <StatCard
          label="Critical and high findings"
          value={critical + high}
          tone={critical > 0 ? 'critical' : high > 0 ? 'danger' : 'neutral'}
          hint={`${critical} critical, ${high} high, ${medium} medium`}
          icon={<ShieldAlert className="h-4 w-4" />}
        />
      </section>

      {/* Recent audits */}
      <Card
        title="Recent audits"
        description="The latest runs from the CLI and from pull request webhooks."
        padded={false}
        actions={
          <Button variant="ghost" size="sm" onClick={() => onNavigateTab('audits')}>
            All audits
          </Button>
        }
      >
        {allAudits.length === 0 ? (
          <EmptyState
            icon={<FileCheck2 className="h-10 w-10" />}
            title="No audits recorded yet"
            description="Run an audit from the terminal with `sceptic audit <path>`, or connect a repository webhook."
            action={
              <Button variant="secondary" size="sm" onClick={() => onNavigateTab('docs')}>
                Read the CLI guide
              </Button>
            }
          />
        ) : (
          <div className={tableClasses.wrap}>
            <table className={tableClasses.table}>
              <caption className="sr-only">Five most recent audits</caption>
              <thead className={tableClasses.head}>
                <tr>
                  <th scope="col" className={tableClasses.th}>Audit</th>
                  <th scope="col" className={tableClasses.th}>Source</th>
                  <th scope="col" className={tableClasses.th}>Status</th>
                  <th scope="col" className={tableClasses.th}>Trust score</th>
                  <th scope="col" className={tableClasses.th}>Verdict</th>
                  <th scope="col" className={tableClasses.th}>Started</th>
                  <th scope="col" className={`${tableClasses.th} text-right`}><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {allAudits.slice(0, 5).map((audit) => {
                  const pr = audit.pull_request;
                  const source = pr
                    ? `${pr.repository || 'Project audit'} #${pr.pr_number || 1}`
                    : 'CLI / in-process';
                  return (
                    <tr key={audit.id} className={tableClasses.row}>
                      <td className={tableClasses.td}>
                        <button
                          type="button"
                          onClick={() => onSelectAudit(audit.id)}
                          className="font-mono text-xs font-semibold text-ink hover:text-accent"
                        >
                          {String(audit.id).slice(0, 8)}
                        </button>
                      </td>
                      <td className={`${tableClasses.td} max-w-[220px] truncate`}>{source}</td>
                      <td className={tableClasses.td}><StatusBadge status={audit.status} /></td>
                      <td className={tableClasses.td}>
                        {typeof audit.trust_score === 'number' ? (
                          <span className={`font-mono font-semibold ${trustTone(audit.trust_score) === 'success' ? 'text-success' : trustTone(audit.trust_score) === 'warning' ? 'text-warning' : 'text-danger'}`}>
                            {audit.trust_score}/100
                          </span>
                        ) : (
                          <span className="text-ink-subtle">-</span>
                        )}
                      </td>
                      <td className={tableClasses.td}><RecommendationBadge value={audit.recommendation} /></td>
                      <td className={`${tableClasses.td} text-xs text-ink-muted`}>{formatTime(audit.started_at || audit.created_at)}</td>
                      <td className={`${tableClasses.td} text-right`}>
                        <Button variant="ghost" size="sm" onClick={() => onSelectAudit(audit.id)}>
                          View<span className="sr-only"> audit {String(audit.id).slice(0, 8)}</span>
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {completed.length > 0 && critical + high === 0 && (
        <p className="flex items-center gap-2 text-xs text-ink-muted">
          <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-hidden />
          No critical or high findings across the audits shown.
        </p>
      )}
    </div>
  );
};
