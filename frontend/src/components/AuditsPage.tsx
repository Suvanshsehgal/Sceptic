import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileCheck2, RefreshCw, Search } from 'lucide-react';
import { fetchAudits } from '../api';
import { useAuth } from '../context/AuthContext';
import { AuditRun } from '../types';
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  PageHeader,
  RecommendationBadge,
  Skeleton,
  StatusBadge,
  fieldClass,
  tableClasses,
  trustTone,
} from './ui';

interface AuditsPageProps {
  onSelectAudit: (id: number | string) => void;
}

const STATUS_OPTIONS = [
  { value: 'ALL', label: 'All statuses' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'RUNNING', label: 'Running' },
  { value: 'QUEUED', label: 'Queued' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'FAILED', label: 'Failed' },
];

function scoreClass(score: number): string {
  const tone = trustTone(score);
  return tone === 'success' ? 'text-success' : tone === 'warning' ? 'text-warning' : 'text-danger';
}

export const AuditsPage: React.FC<AuditsPageProps> = ({ onSelectAudit }) => {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const { token } = useAuth();
  const { data: audits, isLoading, error, refetch, isFetching } = useQuery<AuditRun[]>({
    queryKey: ['audits'],
    queryFn: () => fetchAudits(0, 100),
    refetchInterval: 10000,
    enabled: !!token,
  });

  const allAudits = audits || [];

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return allAudits.filter((audit) => {
      if (statusFilter !== 'ALL' && audit.status !== statusFilter) return false;
      if (!query) return true;
      const repo = audit.pull_request?.repository || '';
      const pr = String(audit.pull_request?.pr_number ?? '');
      const sha = (audit.pull_request?.latest_commit_sha || audit.commit_sha || '').toLowerCase();
      return (
        String(audit.id).toLowerCase().includes(query) ||
        repo.toLowerCase().includes(query) ||
        pr.includes(query) ||
        sha.includes(query)
      );
    });
  }, [allAudits, search, statusFilter]);

  const hasFilters = search.trim() !== '' || statusFilter !== 'ALL';

  if (!token) {
    return (
      <div className="space-y-8">
        <PageHeader title="Audits" description="Every verification run from the CLI and from pull request webhooks." />
        <Card>
          <EmptyState
            icon={<FileCheck2 className="h-9 w-9" />}
            title="Sign in to see audits"
            description="Your audits are private to your account. Sign in from the sidebar to load them."
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audits"
        description="Every verification run from the CLI and from pull request webhooks. Select a row to see its findings."
        actions={
          <Button variant="secondary" onClick={() => refetch()} disabled={isFetching} aria-label="Refresh audits">
            <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} aria-hidden />
            Refresh
          </Button>
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="relative flex-1 sm:max-w-md">
          <Field label="Search" htmlFor="audit-search">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
              <input
                id="audit-search"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Audit ID, repository, commit, or PR number"
                className={`${fieldClass} pl-9`}
              />
            </div>
          </Field>
        </div>
        <div className="sm:w-56">
          <Field label="Status" htmlFor="audit-status">
            <select id="audit-status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className={fieldClass}>
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </Field>
        </div>
        {hasFilters && (
          <Button
            variant="ghost"
            onClick={() => {
              setSearch('');
              setStatusFilter('ALL');
            }}
          >
            Clear filters
          </Button>
        )}
      </div>

      <Card padded={false}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3 text-xs text-ink-muted">
          <span aria-live="polite">
            {isLoading ? 'Loading audits' : `${filtered.length} of ${allAudits.length} audits`}
          </span>
          {isFetching && !isLoading && <span className="text-ink-subtle">Updating</span>}
        </div>

        {isLoading ? (
          <div className="space-y-3 p-5" aria-busy="true">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : error ? (
          <div className="p-5">
            <ErrorBanner title="Could not load audits" message={(error as Error).message} />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<FileCheck2 className="h-10 w-10" />}
            title={allAudits.length === 0 ? 'No audits yet' : 'No audits match these filters'}
            description={
              allAudits.length === 0
                ? 'Run `sceptic audit <path>` in a terminal, or connect a repository webhook.'
                : 'Try a different search term or status.'
            }
            action={hasFilters ? <Button variant="secondary" size="sm" onClick={() => { setSearch(''); setStatusFilter('ALL'); }}>Clear filters</Button> : undefined}
          />
        ) : (
          <div className={tableClasses.wrap}>
            <table className={tableClasses.table}>
              <caption className="sr-only">Audit runs</caption>
              <thead className={tableClasses.head}>
                <tr>
                  <th scope="col" className={tableClasses.th}>Audit</th>
                  <th scope="col" className={tableClasses.th}>Repository</th>
                  <th scope="col" className={tableClasses.th}>Pull request</th>
                  <th scope="col" className={tableClasses.th}>Status</th>
                  <th scope="col" className={tableClasses.th}>Trust score</th>
                  <th scope="col" className={tableClasses.th}>Verdict</th>
                  <th scope="col" className={`${tableClasses.th} text-right`}>Findings</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((audit) => {
                  const pr = audit.pull_request;
                  const sha = (pr?.latest_commit_sha || audit.commit_sha || '').slice(0, 7);
                  return (
                    <tr
                      key={audit.id}
                      className={`${tableClasses.row} cursor-pointer`}
                      onClick={() => onSelectAudit(audit.id)}
                    >
                      <td className={tableClasses.td}>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectAudit(audit.id);
                          }}
                          className="font-mono text-xs font-semibold text-ink hover:text-accent"
                        >
                          {String(audit.id).slice(0, 8)}
                        </button>
                      </td>
                      <td className={`${tableClasses.td} max-w-[220px] truncate`}>
                        {pr?.repository || <span className="text-ink-subtle">Local / CLI</span>}
                      </td>
                      <td className={tableClasses.td}>
                        {pr ? (
                          <span className="font-mono text-xs text-ink-muted">#{pr.pr_number || 1}{sha ? ` · ${sha}` : ''}</span>
                        ) : (
                          <span className="text-ink-subtle">-</span>
                        )}
                      </td>
                      <td className={tableClasses.td}><StatusBadge status={audit.status} /></td>
                      <td className={tableClasses.td}>
                        {typeof audit.trust_score === 'number' ? (
                          <span className={`font-mono font-semibold ${scoreClass(audit.trust_score)}`}>{audit.trust_score}/100</span>
                        ) : (
                          <span className="text-ink-subtle">-</span>
                        )}
                      </td>
                      <td className={tableClasses.td}><RecommendationBadge value={audit.recommendation} /></td>
                      <td className={`${tableClasses.td} text-right font-mono text-ink-muted`}>{audit.findings?.length || 0}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};
