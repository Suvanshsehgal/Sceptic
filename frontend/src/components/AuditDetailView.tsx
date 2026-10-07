import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchAuditById } from '../api';
import { AuditRun, AgentFinding } from '../types';
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
  auditId: number;
  onBack: () => void;
}

export const AuditDetailView: React.FC<AuditDetailViewProps> = ({ auditId, onBack }) => {
  const [selectedAgent, setSelectedAgent] = useState<string>('ALL');
  const [expandedFindings, setExpandedFindings] = useState<Record<number, boolean>>({});

  const { data: audit, isLoading, error } = useQuery<AuditRun>({
    queryKey: ['audit', auditId],
    queryFn: () => fetchAuditById(auditId),
    refetchInterval: 5000,
  });

  const toggleExpand = (findingId: number) => {
    setExpandedFindings((prev) => ({
      ...prev,
      [findingId]: !prev[findingId],
    }));
  };

  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 w-32 bg-slate-800 rounded-md" />
        <div className="h-44 bg-slate-800 rounded-xl" />
        <div className="h-96 bg-slate-800 rounded-xl" />
      </div>
    );
  }

  if (error || !audit) {
    return (
      <div className="space-y-4">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-xs font-semibold text-slate-400 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Audits</span>
        </button>
        <div className="p-6 rounded-xl bg-red-950/40 border border-red-800 text-red-300 text-xs">
          {(error as Error)?.message || 'Audit record not found.'}
        </div>
      </div>
    );
  }

  const pr = audit.pull_request;
  const score = audit.trust_score;
  const findings = audit.findings || [];

  const agentNames = ['ALL', 'Fact-Checker', 'Blind-Tester', 'Security-Guard'];
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
          className="inline-flex items-center gap-2 text-xs font-semibold text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Audits List</span>
        </button>
      </div>

      {/* Main Audit Header Card */}
      <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 space-y-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-6">
          <div className="space-y-1.5">
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-bold text-white font-mono">Audit #{audit.id}</h2>
              <span className={`px-2.5 py-0.5 rounded text-xs font-semibold uppercase ${
                audit.status === 'COMPLETED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                audit.status === 'RUNNING' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20 animate-pulse' :
                audit.status === 'FAILED' ? 'bg-red-500/10 text-red-400 border border-red-500/20' :
                'bg-slate-800 text-slate-400'
              }`}>
                {audit.status}
              </span>
            </div>
            {pr ? (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <GitPullRequest className="h-3.5 w-3.5 text-slate-400" />
                <span className="font-semibold text-slate-200">{pr.repository_full_name}</span>
                <span>·</span>
                <span>PR #{pr.pr_number}</span>
                <span>·</span>
                <span className="font-mono text-slate-400">commit {pr.commit_sha}</span>
                {pr.branch_name && <span>· branch {pr.branch_name}</span>}
              </div>
            ) : (
              <p className="text-xs text-slate-400">CLI / In-Process Synchronous Audit</p>
            )}
          </div>

          {/* Trust Score & Recommendation Badge */}
          <div className="flex items-center gap-4 bg-slate-950/70 p-3.5 rounded-xl border border-slate-800">
            <div>
              <span className="block text-[10px] text-slate-400 uppercase font-semibold">Trust Score</span>
              <span className={`text-2xl font-bold font-mono ${
                typeof score !== 'number' ? 'text-slate-400' :
                score >= 85 ? 'text-emerald-400' :
                score >= 65 ? 'text-yellow-400' : 'text-red-400'
              }`}>
                {typeof score === 'number' ? `${score}/100` : 'Pending'}
              </span>
            </div>
            <div className="h-8 w-px bg-slate-800" />
            <div>
              <span className="block text-[10px] text-slate-400 uppercase font-semibold">Verdict</span>
              <span className={`text-sm font-bold uppercase font-mono ${
                audit.recommendation === 'APPROVE' ? 'text-emerald-400' :
                audit.recommendation === 'REQUEST_CHANGES' ? 'text-yellow-400' :
                audit.recommendation === 'BLOCK' ? 'text-red-400' : 'text-slate-400'
              }`}>
                {audit.recommendation || 'N/A'}
              </span>
            </div>
          </div>
        </div>

        {/* Timestamps & Summary */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div>
            <span className="text-slate-400 block mb-0.5">Started At:</span>
            <span className="text-slate-200 font-mono">{new Date(audit.started_at).toLocaleString()}</span>
          </div>
          <div>
            <span className="text-slate-400 block mb-0.5">Completed At:</span>
            <span className="text-slate-200 font-mono">
              {audit.completed_at ? new Date(audit.completed_at).toLocaleString() : 'In Progress'}
            </span>
          </div>
          <div>
            <span className="text-slate-400 block mb-0.5">Finding Distribution:</span>
            <div className="flex items-center gap-2 font-mono">
              <span className="text-red-400 font-bold">{criticalCount} Crit</span>
              <span className="text-slate-600">·</span>
              <span className="text-orange-400 font-bold">{highCount} High</span>
              <span className="text-slate-600">·</span>
              <span className="text-yellow-400">{mediumCount} Med</span>
              <span className="text-slate-600">·</span>
              <span className="text-blue-400">{lowCount} Low</span>
            </div>
          </div>
        </div>

        {audit.summary && (
          <div className="p-4 rounded-lg bg-slate-950/60 border border-slate-800 text-xs text-slate-300 leading-relaxed font-sans">
            <span className="font-semibold text-slate-200 block mb-1">Synthesizer Assessment:</span>
            {audit.summary}
          </div>
        )}
      </div>

      {/* Agent Findings Section */}
      <div className="space-y-4">
        {/* Agent Filter Tabs */}
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-1.5 p-1 bg-slate-900 border border-slate-800 rounded-lg text-xs">
            {agentNames.map((agent) => (
              <button
                key={agent}
                onClick={() => setSelectedAgent(agent)}
                className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                  selectedAgent === agent
                    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                {agent}
              </button>
            ))}
          </div>

          <span className="text-xs text-slate-400 font-mono">
            Showing {filteredFindings.length} of {findings.length} findings
          </span>
        </div>

        {/* Findings List */}
        {filteredFindings.length === 0 ? (
          <div className="p-12 text-center rounded-xl bg-slate-900 border border-slate-800">
            <CheckCircle2 className="h-10 w-10 text-emerald-400 mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-slate-200">No Findings Found</h3>
            <p className="text-xs text-slate-400 mt-1">
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
                  className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden text-xs"
                >
                  <div
                    onClick={() => toggleExpand(finding.id)}
                    className="p-4 flex items-center justify-between gap-4 cursor-pointer hover:bg-slate-800/40 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <button className="text-slate-400 hover:text-white">
                        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>

                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono uppercase ${
                        sev === 'CRITICAL' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                        sev === 'HIGH' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' :
                        sev === 'MEDIUM' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' :
                        sev === 'LOW' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' :
                        'bg-slate-800 text-slate-300'
                      }`}>
                        {sev}
                      </span>

                      <div>
                        <span className="font-semibold text-slate-200 block sm:inline mr-2">
                          {finding.title}
                        </span>
                        <span className="text-slate-400 font-mono text-[11px]">
                          [{finding.agent_name}]
                        </span>
                      </div>
                    </div>

                    <div className="text-slate-400 font-mono text-[11px] shrink-0">
                      {finding.file_path ? `${finding.file_path}:${finding.line_number || '-'}` : 'Project Scope'}
                    </div>
                  </div>

                  {/* Expanded Body / Evidence */}
                  {isExpanded && (
                    <div className="px-5 pb-5 pt-1 border-t border-slate-800/60 bg-slate-950/40 space-y-3">
                      <div>
                        <span className="font-semibold text-slate-400 uppercase text-[10px] block mb-1">
                          Description
                        </span>
                        <p className="text-slate-300 leading-relaxed font-sans">{finding.description}</p>
                      </div>

                      {finding.evidence && (
                        <div>
                          <span className="font-semibold text-slate-400 uppercase text-[10px] block mb-1">
                            Evidence & Trace
                          </span>
                          <pre className="p-3 rounded-lg bg-slate-900 border border-slate-800 text-emerald-400/90 font-mono text-[11px] overflow-x-auto whitespace-pre-wrap">
                            {finding.evidence}
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
