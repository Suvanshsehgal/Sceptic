import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { auditStreamUrl, fetchAuditById } from '../api';
import { AuditRun, AgentFinding, AuditProgress } from '../types';
import { 
  ArrowLeft, 
  ShieldCheck, 
  ShieldAlert, 
  Clock, 
  GitPullRequest, 
  FileCode2, 
  AlertTriangle,
  Info,
  CheckCircle2,
  Terminal,
  Cpu,
  Layers,
  ChevronDown,
  ChevronRight
} from 'lucide-react';

interface AuditDetailViewProps {
  auditId: number | string;
  onBack: () => void;
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
  const findings = audit.findings || [];

  const dynamicAgents = Array.from(new Set(findings.map((f) => f.agent_name))).filter(Boolean);
  const agentNames = ['ALL', ...Array.from(new Set(['Fact-Checker', 'Blind-Tester', 'Security-Guard', ...dynamicAgents]))];
  const filteredFindings = selectedAgent === 'ALL'
    ? findings
    : findings.filter((f) => f.agent_name.toLowerCase().includes(selectedAgent.toLowerCase()) || f.agent_name === selectedAgent);

  const criticalCount = findings.filter((f) => f.severity === 'CRITICAL').length;
  const highCount = findings.filter((f) => f.severity === 'HIGH').length;
  const mediumCount = findings.filter((f) => f.severity === 'MEDIUM').length;
  const lowCount = findings.filter((f) => f.severity === 'LOW').length;

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <button
          onClick={onBack}
          className="inline-flex items-center gap-2 text-xs font-semibold text-ink-muted hover:text-ink transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Audits List</span>
        </button>
      </div>

      {/* Main Audit Header Card */}
      <div className="p-6 rounded-xl bg-surface border border-line space-y-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-6">
          <div className="space-y-1.5">
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-bold text-ink font-mono">Audit #{audit.id}</h2>
              <span className={`px-2.5 py-0.5 rounded text-xs font-semibold uppercase ${
                audit.status === 'COMPLETED' ? 'bg-accent/10 text-accent border border-accent/30' :
                audit.status === 'RUNNING' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20 animate-pulse' :
                audit.status === 'FAILED' ? 'bg-danger/10 text-danger border border-red-500/20' :
                'bg-surface-raised text-ink-muted'
              }`}>
                {audit.status}
              </span>
            </div>
            {pr ? (
              <div className="flex items-center gap-2 text-xs text-ink-muted">
                <GitPullRequest className="h-3.5 w-3.5 text-ink-muted" />
                <span className="font-semibold text-ink">{pr.repository || pr.repository_full_name || 'Project Audit'}</span>
                <span>·</span>
                <span>PR #{pr.pr_number || 1}</span>
                <span>·</span>
                <span className="font-mono text-ink-muted">commit {String(pr.latest_commit_sha || pr.commit_sha || audit.commit_sha || 'cli-local').substring(0, 7)}</span>
                {pr.branch_name && <span>· branch {pr.branch_name}</span>}
              </div>
            ) : (
              <p className="text-xs text-ink-muted">CLI / In-Process Synchronous Audit</p>
            )}
          </div>

          {/* Trust Score & Recommendation Badge */}
          <div className="flex items-center gap-4 bg-canvas p-3.5 rounded-xl border border-line">
            <div>
              <span className="block text-[10px] text-ink-muted uppercase font-semibold">Trust Score</span>
              <span className={`text-2xl font-bold font-mono ${
                typeof score !== 'number' ? 'text-ink-muted' :
                score >= 85 ? 'text-accent' :
                score >= 65 ? 'text-warning' : 'text-danger'
              }`}>
                {typeof score === 'number' ? `${score}/100` : 'Pending'}
              </span>
            </div>
            <div className="h-8 w-px bg-surface-raised" />
            <div>
              <span className="block text-[10px] text-ink-muted uppercase font-semibold">Verdict</span>
              <span className={`text-sm font-bold uppercase font-mono ${
                audit.recommendation === 'APPROVE' ? 'text-accent' :
                audit.recommendation === 'REQUEST_CHANGES' ? 'text-warning' :
                audit.recommendation === 'BLOCK' ? 'text-danger' : 'text-ink-muted'
              }`}>
                {audit.recommendation || 'N/A'}
              </span>
            </div>
          </div>
        </div>

        {/* Timestamps & Summary */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div>
            <span className="text-ink-muted block mb-0.5">Started At:</span>
            <span className="text-ink font-mono">{new Date(audit.started_at).toLocaleString()}</span>
          </div>
          <div>
            <span className="text-ink-muted block mb-0.5">Completed At:</span>
            <span className="text-ink font-mono">
              {audit.completed_at ? new Date(audit.completed_at).toLocaleString() : 'In Progress'}
            </span>
          </div>
          <div>
            <span className="text-ink-muted block mb-0.5">Finding Distribution:</span>
            <div className="flex items-center gap-2 font-mono">
              <span className="text-danger font-bold">{criticalCount} Crit</span>
              <span className="text-ink-subtle">·</span>
              <span className="text-orange-400 font-bold">{highCount} High</span>
              <span className="text-ink-subtle">·</span>
              <span className="text-warning">{mediumCount} Med</span>
              <span className="text-ink-subtle">·</span>
              <span className="text-blue-400">{lowCount} Low</span>
            </div>
          </div>
        </div>

        {audit.summary && (
          <div className="p-4 rounded-lg bg-canvas border border-line text-xs text-ink leading-relaxed font-sans">
            <span className="font-semibold text-ink block mb-1">Synthesizer Assessment:</span>
            {audit.summary}
          </div>
        )}
      </div>

      {/* Live progress (Server-Sent Events) */}
      {streamState !== 'idle' && (
        <div className="p-5 rounded-xl bg-surface border border-line space-y-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-ink uppercase tracking-wider">
              {streamState === 'live' ? 'Live progress' : 'Progress stream closed'}
            </span>
            {streamState === 'live' && <span className="text-accent font-mono animate-pulse">streaming</span>}
          </div>
          {liveProgress && Object.keys(liveProgress.agents || {}).length > 0 ? (
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {Object.entries(liveProgress.agents).map(([agent, info]) => (
                <li key={agent} className="flex items-center justify-between p-2 rounded-lg bg-canvas border border-line">
                  <span className="font-mono text-ink">{agent}</span>
                  <span className="text-accent">done · {info.findings} findings</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-ink-muted">Waiting for the first agent to finish...</p>
          )}
        </div>
      )}

      {/* Agent Findings Section */}
      <div className="space-y-4">
        {/* Agent Filter Tabs */}
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-1.5 p-1 bg-surface border border-line rounded-lg text-xs">
            {agentNames.map((agent) => (
              <button
                key={agent}
                onClick={() => setSelectedAgent(agent)}
                className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                  selectedAgent === agent
                    ? 'bg-accent/15 text-accent border border-accent/30'
                    : 'text-ink-muted hover:text-ink'
                }`}
              >
                {agent}
              </button>
            ))}
          </div>

          <span className="text-xs text-ink-muted font-mono">
            Showing {filteredFindings.length} of {findings.length} findings
          </span>
        </div>

        {/* Findings List */}
        {filteredFindings.length === 0 ? (
          <div className="p-12 text-center rounded-xl bg-surface border border-line">
            <CheckCircle2 className="h-10 w-10 text-accent mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-ink">No Findings Found</h3>
            <p className="text-xs text-ink-muted mt-1">
              No issues or anomalies were reported by the selected verification agent for this audit.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredFindings.map((finding) => {
              const isExpanded = !!expandedFindings[finding.id];
              const sev = (finding.severity || 'INFO').toUpperCase();

              return (
                <div
                  key={finding.id}
                  className="rounded-xl bg-surface border border-line overflow-hidden text-xs"
                >
                  <div
                    onClick={() => toggleExpand(finding.id)}
                    className="p-4 flex items-center justify-between gap-4 cursor-pointer hover:bg-surface-raised/60 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <button className="text-ink-muted hover:text-ink">
                        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>

                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono uppercase ${
                        sev === 'CRITICAL' ? 'bg-danger/10 text-danger border border-red-500/30' :
                        sev === 'HIGH' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' :
                        sev === 'MEDIUM' ? 'bg-yellow-500/20 text-warning border border-yellow-500/30' :
                        sev === 'LOW' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' :
                        'bg-surface-raised text-ink'
                      }`}>
                        {sev}
                      </span>

                      <div>
                        <span className="font-semibold text-ink block sm:inline mr-2">
                          {finding.title}
                        </span>
                        <span className="text-ink-muted font-mono text-[11px]">
                          [{finding.agent_name}]
                        </span>
                      </div>
                    </div>

                    <div className="text-ink-muted font-mono text-[11px] shrink-0">
                      {finding.file_path ? `${finding.file_path}:${finding.line_number || '-'}` : 'Project Scope'}
                    </div>
                  </div>

                  {/* Expanded Body / Evidence */}
                  {isExpanded && (
                    <div className="px-5 pb-5 pt-1 border-t border-line bg-canvas space-y-3">
                      <div>
                        <span className="font-semibold text-ink-muted uppercase text-[10px] block mb-1">
                          Description
                        </span>
                        <p className="text-ink leading-relaxed font-sans">{finding.description}</p>
                      </div>

                      {finding.evidence && (
                        <div>
                          <span className="font-semibold text-ink-muted uppercase text-[10px] block mb-1">
                            Evidence & Trace
                          </span>
                          <pre className="p-3 rounded-lg bg-surface border border-line text-accent/90 font-mono text-[11px] overflow-x-auto whitespace-pre-wrap">
                            {typeof finding.evidence === 'object'
                              ? JSON.stringify(finding.evidence, null, 2)
                              : String(finding.evidence)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
