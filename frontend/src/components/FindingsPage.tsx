import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, ChevronDown, ChevronRight, ExternalLink, ShieldAlert } from 'lucide-react';
import { fetchAudits } from '../api';
import { useAuth } from '../context/AuthContext';
import { AgentFinding, AuditRun } from '../types';
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  PageHeader,
  SeverityBadge,
  Skeleton,
  fieldClass,
} from './ui';

interface FindingsPageProps {
  onSelectAudit: (auditId: string | number) => void;
}

interface FindingWithParent extends AgentFinding {
  audit_id: string | number;
  repo_name: string;
}

const SEVERITIES = ['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'];
const AGENTS = ['Fact-Checker', 'Blind-Tester', 'Security-Guard', 'Leak-Hunter', 'Purana-Saman', 'Jhooti-Docstring'];

export const FindingsPage: React.FC<FindingsPageProps> = ({ onSelectAudit }) => {
  const [severityFilter, setSeverityFilter] = useState('ALL');
  const [agentFilter, setAgentFilter] = useState('ALL');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const { token } = useAuth();
  const { data: audits, isLoading, error } = useQuery<AuditRun[]>({
    queryKey: ['audits'],
    queryFn: () => fetchAudits(0, 100),
    enabled: !!token,
  });

  const allFindings: FindingWithParent[] = useMemo(
    () =>
      (audits || []).flatMap((audit) =>
        (audit.findings || []).map((f) => ({
          ...f,
          audit_id: audit.id,
          repo_name: audit.pull_request?.repository || 'Project audit',
        }))
      ),
    [audits]
  );

  const agentOptions = useMemo(
    () => Array.from(new Set([...AGENTS, ...allFindings.map((f) => f.agent_name)])).filter(Boolean),
    [allFindings]
  );

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return allFindings
      .filter((f) => severityFilter === 'ALL' || (f.severity || '').toUpperCase() === severityFilter)
      .filter((f) => agentFilter === 'ALL' || f.agent_name === agentFilter)
      .filter(
        (f) =>
          !query ||
          f.title?.toLowerCase().includes(query) ||
          f.description?.toLowerCase().includes(query) ||
          f.file_path?.toLowerCase().includes(query) ||
          String(f.audit_id).includes(query)
      );
  }, [allFindings, severityFilter, agentFilter, search]);

  const counts = useMemo(() => {
    const total: Record<string, number> = {};
    allFindings.forEach((f) => {
      const key = (f.severity || 'INFO').toUpperCase();
      total[key] = (total[key] || 0) + 1;
    });
    return total;
  }, [allFindings]);

  if (!token) {
    return (
      <div className="space-y-8">
        <PageHeader title="Findings" description="Issues reported across all audits, with severity and location." />
        <Card>
          <EmptyState
            icon={<ShieldAlert className="h-9 w-9" />}
            title="Sign in to see findings"
            description="Findings come from your audits. Sign in from the sidebar to load them."
          />
        </Card>
      </div>
    );
  }

  const toggle = (id: string | number) =>
    setExpanded((prev) => ({ ...prev, [String(id)]: !prev[String(id)] }));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Findings"
        description="Every issue reported across all audits, with its severity, the agent that found it, and where it is."
      />

      {/* Severity summary doubles as a filter */}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by severity">
        {SEVERITIES.map((sev) => {
          const count = sev === 'ALL' ? allFindings.length : counts[sev] || 0;
          const active = severityFilter === sev;
          return (
            <button
              key={sev}
              type="button"
              aria-pressed={active}
              onClick={() => setSeverityFilter(sev)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                active ? 'border-accent/40 bg-accent/10 text-accent' : 'border-line bg-surface text-ink-muted hover:text-ink'
              }`}
            >
              {sev === 'ALL' ? 'All' : sev.charAt(0) + sev.slice(1).toLowerCase()}
              <span className="ml-2 font-mono text-ink-subtle">{count}</span>
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_220px]">
        <Field label="Search" htmlFor="finding-search">
          <input
            id="finding-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Title, description, file, or audit ID"
            className={fieldClass}
          />
        </Field>
        <Field label="Agent" htmlFor="finding-agent">
          <select id="finding-agent" value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} className={fieldClass}>
            <option value="ALL">All agents</option>
            {agentOptions.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </Field>
      </div>

      {isLoading ? (
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}
        </div>
      ) : error ? (
        <ErrorBanner title="Could not load findings" message={(error as Error).message} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={allFindings.length === 0 ? <CheckCircle2 className="h-10 w-10 text-success" /> : <ShieldAlert className="h-10 w-10" />}
          title={allFindings.length === 0 ? 'No findings recorded' : 'No findings match these filters'}
          description={allFindings.length === 0 ? 'Audits that report no issues show up here as clean runs.' : 'Clear the filters to see everything.'}
        />
      ) : (
        <Card padded={false}>
          <p className="border-b border-line px-5 py-3 text-xs text-ink-muted" aria-live="polite">
            Showing {filtered.length} of {allFindings.length} findings
          </p>
          <ul className="divide-y divide-line">
            {filtered.map((finding) => {
              const isOpen = !!expanded[finding.id];
              const location = finding.file_path ? `${finding.file_path}${finding.line_number ? `:${finding.line_number}` : ''}` : 'Project scope';
              return (
                <li key={finding.id}>
                  <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
                    <button
                      type="button"
                      onClick={() => toggle(finding.id)}
                      aria-expanded={isOpen}
                      className="flex min-w-0 flex-1 items-start gap-3 text-left"
                    >
                      <span className="mt-0.5 text-ink-subtle" aria-hidden>
                        {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </span>
                      <span className="min-w-0 space-y-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <SeverityBadge severity={finding.severity} />
                          <span className="text-sm font-medium text-ink">{finding.title}</span>
                        </span>
                        <span className="block font-mono text-xs text-ink-subtle">
                          {finding.agent_name} · {location}
                        </span>
                      </span>
                    </button>
                    <Button variant="ghost" size="sm" onClick={() => onSelectAudit(finding.audit_id)} className="self-start sm:self-center">
                      Audit {String(finding.audit_id).slice(0, 8)}
                      <ExternalLink className="h-3 w-3" aria-hidden />
                    </Button>
                  </div>
                  {isOpen && (
                    <div className="space-y-4 border-t border-line bg-canvas/40 px-5 pb-5 pt-4 pl-12">
                      <div>
                        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">Description</h3>
                        <p className="mt-1 text-sm leading-relaxed text-ink-muted">{finding.description || 'No description provided.'}</p>
                      </div>
                      {finding.recommendation && (
                        <div>
                          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">Recommendation</h3>
                          <p className="mt-1 text-sm leading-relaxed text-ink-muted">{finding.recommendation}</p>
                        </div>
                      )}
                      {finding.evidence && (
                        <div>
                          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">Evidence</h3>
                          <pre className="mt-1 max-h-72 overflow-auto rounded-lg border border-line bg-surface p-3 font-mono text-[11px] leading-relaxed text-accent/90">
                            {typeof finding.evidence === 'object' ? JSON.stringify(finding.evidence, null, 2) : String(finding.evidence)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
};
