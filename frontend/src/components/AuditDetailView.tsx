import React, { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { auditStreamUrl, fetchAuditById } from '../api';
import { AuditRun, AuditProgress } from '../types';
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  ExternalLink,
  GitPullRequest,
} from 'lucide-react';
import {
  Badge,
  SEVERITY_ORDER,
  SectionTitle,
  SeverityBadge,
  SeverityBar,
  StatusBadge,
  SymbolStatus,
  VerdictCard,
  type SymbolState,
} from './ui';

interface AuditDetailViewProps {
  auditId: number | string;
  onBack: () => void;
}

/* The six verification agents, in the order the CLI prints them. */
const VERIFICATION_AGENTS = [
  'Fact-Checker',
  'Blind-Tester',
  'Security-Guard',
  'Leak-Hunter',
  'Purana-Saman',
  'Jhooti-Docstring',
] as const;

const SEVERITY_RANK: Record<string, number> = Object.fromEntries(SEVERITY_ORDER.map((key, index) => [key, index]));

const SEVERITY_TEXT: Record<string, string> = {
  CRITICAL: 'text-critical',
  HIGH: 'text-danger',
  MEDIUM: 'text-warning',
  LOW: 'text-info',
  INFO: 'text-ink-muted',
};

function formatDuration(startIso?: string | null, endIso?: string | null): string | null {
  if (!startIso || !endIso) return null;
  const seconds = (new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000;
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

/* Per-agent state. The API stores the statuses the worker reported at completion. For older audits that do not have
   them, a status is only inferred from findings, and the table says so. */
function agentStateFor(name: string, reported: Record<string, string> | null, ownFindings: { status?: string }[]): { state: SymbolState; word: string } {
  if (reported) {
    const value = (reported[name] || '').toUpperCase();
    if (value === 'PARTIAL_FAILURE') return { state: 'warn', word: 'PARTIAL' };
    if (value === 'OK') return { state: 'ok', word: 'OK' };
    return { state: 'info', word: 'NOT RUN' };
  }
  const errored = ownFindings.some((f) => String(f.status || '').toUpperCase() === 'ERROR');
  return errored ? { state: 'warn', word: 'PARTIAL' } : { state: 'info', word: 'NOT RECORDED' };
}

export const AuditDetailView: React.FC<AuditDetailViewProps> = ({ auditId, onBack }) => {
  const [selectedAgent, setSelectedAgent] = useState<string>('ALL');
  const [expandedFindings, setExpandedFindings] = useState<Record<string, boolean>>({});

  const { data: audit, isLoading, error } = useQuery<AuditRun>({
    queryKey: ['audit', auditId],
    queryFn: () => fetchAuditById(auditId),
    refetchInterval: 5000,
  });
  const queryClient = useQueryClient();
  const [liveProgress, setLiveProgress] = useState<AuditProgress | null>(null);
  const [streamState, setStreamState] = useState<'idle' | 'live' | 'closed'>('idle');

  // While the audit is running, stream its progress over Server-Sent Events instead of waiting for the next poll.
  const auditStatus = audit?.status;
  useEffect(() => {
    if (!auditStatus || auditStatus === 'COMPLETED' || auditStatus === 'FAILED') {
      return;
    }
    if (typeof EventSource === 'undefined') {
      return;
    }
    let token: string | null = null;
    try {
      token = localStorage.getItem('sceptic_token');
    } catch {
      token = null;
    }
    const source = new EventSource(auditStreamUrl(auditId, token));
    setStreamState('live');
    source.addEventListener('progress', (event) => {
      const data = JSON.parse((event as MessageEvent).data);
      setLiveProgress(data.progress ?? null);
    });
    source.addEventListener('done', () => {
      source.close();
      setStreamState('closed');
      queryClient.invalidateQueries({ queryKey: ['audit', auditId] });
    });
    source.onerror = () => {
      source.close();
      setStreamState('closed');
    };
    return () => source.close();
  }, [auditStatus, auditId, queryClient]);

  const toggleExpand = (findingId: string | number) => {
    setExpandedFindings((prev) => ({
      ...prev,
      [String(findingId)]: !prev[String(findingId)],
    }));
  };

  const findings = audit?.findings ?? [];

  // Derived values. They are computed before any early return so the hook order stays fixed.
  const severityCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const f of findings) {
      const key = (f.severity || 'INFO').toUpperCase();
      counts[key] = (counts[key] || 0) + 1;
    }
    return counts;
  }, [findings]);

  const sortedFindings = useMemo(
    () => [...findings].sort((a, b) => {
      const rank = (f: { severity?: string }) => SEVERITY_RANK[(f.severity || 'INFO').toUpperCase()] ?? 99;
      return rank(a) - rank(b) || String(a.title).localeCompare(String(b.title));
    }),
    [findings],
  );

  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 w-32 bg-surface-raised rounded-md" />
        <div className="h-44 bg-surface-raised rounded-xl" />
        <div className="h-96 bg-surface-raised rounded-xl" />
      </div>
    );
  }

  if (error || !audit) {
    return (
      <div className="space-y-4">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-xs font-semibold text-ink-muted hover:text-ink"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Audits</span>
        </button>
        <div className="p-6 rounded-xl bg-danger/10 border border-red-800 text-danger text-xs">
          {(error as Error)?.message || 'Audit record not found.'}
        </div>
      </div>
    );
  }

  const pr = audit.pull_request;
  const score = audit.trust_score;
  const reportedStatuses = audit.progress?.statuses && Object.keys(audit.progress.statuses).length > 0
    ? audit.progress.statuses
    : null;
  const duration = formatDuration(audit.started_at, audit.completed_at);

  const dynamicAgents = Array.from(new Set(findings.map((f) => f.agent_name))).filter(Boolean);
  const agentNames = ['ALL', ...Array.from(new Set<string>([...VERIFICATION_AGENTS, ...dynamicAgents]))];
  const filteredFindings = selectedAgent === 'ALL'
    ? sortedFindings
    : sortedFindings.filter((f) => f.agent_name === selectedAgent);

  return (
    <div className="space-y-8">
      <div>
        <button
          onClick={onBack}
          className="inline-flex items-center gap-2 text-xs font-semibold text-ink-muted hover:text-ink transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Audits</span>
        </button>
      </div>

      {/* Header: identity, status and timing, in the CLI's brand-bar style */}
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="font-mono text-[22px] font-semibold tracking-tight text-ink">Audit #{audit.id}</h2>
            <StatusBadge status={audit.status} />
          </div>
          {pr ? (
            <div className="flex flex-wrap items-center gap-2 text-[13px] text-ink-muted">
              <GitPullRequest className="h-3.5 w-3.5" aria-hidden />
              <span className="font-medium text-ink">{pr.repository || pr.repository_full_name || 'Project audit'}</span>
              <span aria-hidden>·</span>
              <span>PR #{pr.pr_number || 1}</span>
              <span aria-hidden>·</span>
              <span className="font-mono">commit {String(pr.latest_commit_sha || pr.commit_sha || audit.commit_sha || 'cli-local').substring(0, 7)}</span>
              {pr.branch_name && (<><span aria-hidden>·</span><span>branch {pr.branch_name}</span></>)}
            </div>
          ) : (
            <p className="text-[13px] text-ink-muted">CLI audit · run in-process</p>
          )}
        </div>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-[13px] md:text-right">
          <div>
            <dt className="text-ink-subtle">Started</dt>
            <dd className="tabular font-mono text-ink">{new Date(audit.started_at ?? audit.created_at).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-ink-subtle">Duration</dt>
            <dd className="tabular font-mono text-ink">
              {duration ?? (audit.completed_at ? '—' : 'In progress')}
            </dd>
          </div>
        </dl>
      </div>

      {/* Verdict: the CLI's verdict panel */}
      <VerdictCard
        title={`Verdict · ${audit.commit_sha && audit.commit_sha !== 'cli-local' ? 'pull request' : 'audit'} result`}
        score={score}
        recommendation={audit.recommendation}
        summary={audit.summary}
        footer={audit.trace_url ? (
          <a
            href={audit.trace_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 font-mono text-xs text-accent hover:underline"
          >
            Agent trace in Langfuse
            <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        ) : null}
      />

      {/* Severity breakdown and agent status, side by side on wide screens */}
      <div className="grid gap-6 lg:grid-cols-5">
        <section className="space-y-4 rounded-lg border border-line bg-surface p-5 lg:col-span-2">
          <SectionTitle aside={`${findings.length} total`}>Severity</SectionTitle>
          <SeverityBar counts={severityCounts} />
        </section>

        <section className="space-y-4 rounded-lg border border-line bg-surface p-5 lg:col-span-3">
          <SectionTitle aside={reportedStatuses ? 'as reported' : 'inferred from findings'}>Agents</SectionTitle>
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-ink-subtle">
                <th className="py-2 font-medium">Agent</th>
                <th className="py-2 font-medium">Status</th>
                <th className="py-2 text-right font-medium">Findings</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {VERIFICATION_AGENTS.map((name) => {
                const own = findings.filter((f) => f.agent_name === name);
                const { state, word } = agentStateFor(name, reportedStatuses, own);
                return (
                  <tr key={name}>
                    <td className="py-2.5 font-mono text-ink">{name}</td>
                    <td className="py-2.5"><SymbolStatus state={state} word={word} /></td>
                    <td className="tabular py-2.5 text-right font-mono text-ink-muted">{own.length}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      </div>

      {/* Live progress (Server-Sent Events) */}
      {streamState !== 'idle' && (
        <section className="space-y-3 rounded-lg border border-line bg-surface p-5">
          <SectionTitle aside={streamState === 'live' ? 'streaming' : 'closed'}>
            {streamState === 'live' ? 'Live progress' : 'Progress stream closed'}
          </SectionTitle>
          {liveProgress && Object.keys(liveProgress.agents || {}).length > 0 ? (
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {Object.entries(liveProgress.agents).map(([agent, info]) => (
                <li key={agent} className="flex items-center justify-between rounded-md border border-line bg-canvas px-3 py-2 text-[13px]">
                  <span className="font-mono text-ink">{agent}</span>
                  <span className="flex items-center gap-2 text-ink-muted">
                    <SymbolStatus state="ok" word="DONE" />
                    <span className="tabular font-mono">{info.findings} findings</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-ink-muted">Waiting for the first agent to finish…</p>
          )}
        </section>
      )}

      {/* Findings */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionTitle aside={`${filteredFindings.length} of ${findings.length} shown`}>Findings</SectionTitle>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-xs" role="tablist" aria-label="Filter by agent">
          {agentNames.map((agent) => (
            <button
              key={agent}
              role="tab"
              aria-selected={selectedAgent === agent}
              onClick={() => setSelectedAgent(agent)}
              className={`rounded-md border px-3 py-1.5 font-medium transition-colors ${
                selectedAgent === agent
                  ? 'border-accent/40 bg-accent/10 text-accent'
                  : 'border-line text-ink-muted hover:text-ink'
              }`}
            >
              {agent}
            </button>
          ))}
        </div>

        {filteredFindings.length === 0 ? (
          <div className="rounded-lg border border-line bg-surface p-10 text-center">
            <CheckCircle2 className="mx-auto mb-3 h-9 w-9 text-success" aria-hidden />
            <h3 className="text-sm font-medium text-ink">No findings</h3>
            <p className="mt-1 text-[13px] text-ink-muted">
              The selected agent reported nothing for this audit.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
            {filteredFindings.map((finding) => {
              const isExpanded = !!expandedFindings[String(finding.id)];
              const sev = (finding.severity || 'INFO').toUpperCase();
              const location = finding.file_path
                ? `${finding.file_path}${finding.line_number ? `:${finding.line_number}` : ''}`
                : 'project';

              return (
                <li key={finding.id}>
                  <button
                    type="button"
                    onClick={() => toggleExpand(finding.id)}
                    aria-expanded={isExpanded}
                    className="flex w-full items-center gap-4 px-4 py-3 text-left transition-colors hover:bg-surface-raised/60"
                  >
                    <span className="text-ink-subtle" aria-hidden>
                      {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </span>
                    <span className={`w-20 shrink-0 font-mono text-[12px] font-semibold uppercase ${SEVERITY_TEXT[sev] ?? 'text-ink-muted'}`}>
                      {sev}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium text-ink">{finding.title}</span>
                      <span className="block font-mono text-[11px] text-ink-subtle">[{finding.agent_name}]</span>
                    </span>
                    <span className="hidden shrink-0 truncate font-mono text-[11px] text-ink-subtle md:block md:max-w-[16rem]">
                      {location}
                    </span>
                  </button>

                  {isExpanded && (
                    <div className="space-y-4 border-t border-line bg-canvas px-5 pb-5 pt-4 text-[13px]">
                      <div className="flex flex-wrap items-center gap-3">
                        <SeverityBadge severity={sev} />
                        {finding.status && <Badge tone="neutral">{String(finding.status).toLowerCase()}</Badge>}
                        <span className="font-mono text-[11px] text-ink-subtle md:hidden">{location}</span>
                      </div>
                      <div>
                        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">Description</div>
                        <p className="leading-relaxed text-ink-muted">{finding.description}</p>
                      </div>
                      {finding.recommendation && (
                        <div>
                          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">Recommendation</div>
                          <p className="leading-relaxed text-ink-muted">{finding.recommendation}</p>
                        </div>
                      )}
                      {finding.evidence && (
                        <div>
                          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">Evidence</div>
                          <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-line bg-surface p-3 font-mono text-[11px] text-ink-muted">
                            {typeof finding.evidence === 'object'
                              ? JSON.stringify(finding.evidence, null, 2)
                              : String(finding.evidence)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {/* The CLI's symbol legend */}
        <p className="font-mono text-[11px] text-ink-subtle">
          ✔ OK &nbsp; ✖ FAIL &nbsp; ▲ PARTIAL (an agent failed; the audit is not approved) &nbsp; • INFO
        </p>
      </section>
    </div>
  );
};
