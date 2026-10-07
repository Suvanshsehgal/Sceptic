import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchAudits } from '../api';
import { AuditRun, AgentFinding } from '../types';
import { 
  AlertTriangle, 
  Search, 
  Filter, 
  ShieldAlert, 
  FileCode2, 
  ExternalLink,
  ChevronDown,
  ChevronRight,
  CheckCircle2
} from 'lucide-react';

interface FindingsPageProps {
  onSelectAudit: (auditId: number) => void;
}

export const FindingsPage: React.FC<FindingsPageProps> = ({ onSelectAudit }) => {
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');
  const [agentFilter, setAgentFilter] = useState<string>('ALL');
  const [search, setSearch] = useState<string>('');
  const [expandedFindings, setExpandedFindings] = useState<Record<number, boolean>>({});

  const { data: audits, isLoading, error } = useQuery<AuditRun[]>({
    queryKey: ['audits'],
    queryFn: () => fetchAudits(0, 100),
  });

  const toggleExpand = (id: number) => {
    setExpandedFindings((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  // Flatten findings across audits while retaining parent audit metadata
  interface FindingWithParent extends AgentFinding {
    audit_id: number;
    repo_name?: string;
  }

  const allFindings: FindingWithParent[] = (audits || []).flatMap((audit) =>
    (audit.findings || []).map((f) => ({
      ...f,
      audit_id: audit.id,
      repo_name: audit.pull_request?.repository_full_name,
    }))
  );

  const filtered = allFindings.filter((f) => {
    const matchesSev = severityFilter === 'ALL' || f.severity?.toUpperCase() === severityFilter;
    const matchesAgent = agentFilter === 'ALL' || f.agent_name?.toLowerCase().includes(agentFilter.toLowerCase());
    const matchesSearch =
      search === '' ||
      f.title?.toLowerCase().includes(search.toLowerCase()) ||
      f.description?.toLowerCase().includes(search.toLowerCase()) ||
      f.file_path?.toLowerCase().includes(search.toLowerCase()) ||
      f.audit_id.toString().includes(search);

    return matchesSev && matchesAgent && matchesSearch;
  });

  return (
    <div className="space-y-6">
      {/* Search and Filters */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search by title, description, file, audit #..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 placeholder-slate-500 text-xs focus:outline-none focus:border-emerald-500/50"
          />
        </div>

        <div className="flex items-center gap-3">
          {/* Severity Dropdown */}
          <div className="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs">
            <ShieldAlert className="h-3.5 w-3.5 text-slate-400" />
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="bg-transparent text-slate-300 focus:outline-none"
            >
              <option value="ALL">All Severities</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
              <option value="INFO">Info</option>
            </select>
          </div>

          {/* Agent Dropdown */}
          <div className="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs">
            <Filter className="h-3.5 w-3.5 text-slate-400" />
            <select
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              className="bg-transparent text-slate-300 focus:outline-none"
            >
              <option value="ALL">All Agents</option>
              <option value="Fact-Checker">Fact-Checker</option>
              <option value="Blind-Tester">Blind-Tester</option>
              <option value="Security-Guard">Security-Guard</option>
            </select>
          </div>
        </div>
      </div>

      {/* Main List */}
      {isLoading ? (
        <div className="p-12 text-center text-slate-400 text-xs animate-pulse">
          Loading findings repository...
        </div>
      ) : error ? (
        <div className="p-8 text-center text-red-400 text-xs">
          Failed to load findings: {(error as Error).message}
        </div>
      ) : filtered.length === 0 ? (
        <div className="p-16 text-center rounded-xl bg-slate-900 border border-slate-800">
          <CheckCircle2 className="h-10 w-10 text-emerald-400 mx-auto mb-3" />
          <h3 className="text-sm font-semibold text-slate-200">No Findings Match Your Filters</h3>
          <p className="text-xs text-slate-400 mt-1">
            No issues found under the selected severity and agent criteria.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((finding) => {
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

                  <div className="flex items-center gap-4 shrink-0">
                    <div className="text-slate-400 font-mono text-[11px] hidden md:block">
                      {finding.file_path ? `${finding.file_path}:${finding.line_number || '-'}` : 'Project Scope'}
                    </div>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectAudit(finding.audit_id);
                      }}
                      className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-emerald-400 font-sans text-xs transition-colors flex items-center gap-1"
                    >
                      <span>Audit #{finding.audit_id}</span>
                      <ExternalLink className="h-3 w-3" />
                    </button>
                  </div>
                </div>

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
  );
};
