import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchAudits } from '../api';
import { AuditRun } from '../types';
import { 
  FileCheck2, 
  Search, 
  Filter, 
  Clock, 
  ExternalLink,
  GitPullRequest,
  CheckCircle,
  AlertOctagon,
  RefreshCw
} from 'lucide-react';

interface AuditsPageProps {
  onSelectAudit: (id: number) => void;
}

export const AuditsPage: React.FC<AuditsPageProps> = ({ onSelectAudit }) => {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const { data: audits, isLoading, error, refetch, isFetching } = useQuery<AuditRun[]>({
    queryKey: ['audits'],
    queryFn: () => fetchAudits(0, 100),
    refetchInterval: 10000,
  });

  const allAudits = audits || [];

  const filteredAudits = allAudits.filter((audit) => {
    const matchesStatus = statusFilter === 'ALL' || audit.status === statusFilter;
    const repo = audit.pull_request?.repository_full_name || '';
    const prNum = audit.pull_request?.pr_number?.toString() || '';
    const sha = audit.pull_request?.commit_sha || '';
    const idStr = audit.id.toString();

    const matchesSearch = 
      idStr.includes(search) ||
      repo.toLowerCase().includes(search.toLowerCase()) ||
      prNum.includes(search) ||
      sha.toLowerCase().includes(search.toLowerCase());

    return matchesStatus && matchesSearch;
  });

  return (
    <div className="space-y-6">
      {/* Controls & Filter Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
        {/* Search Input */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search by Audit ID, repository, commit SHA, PR #..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 placeholder-slate-500 text-xs focus:outline-none focus:border-emerald-500/50"
          />
        </div>

        {/* Filter Dropdown & Refresh */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs">
            <Filter className="h-3.5 w-3.5 text-slate-400" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-transparent text-slate-300 focus:outline-none"
            >
              <option value="ALL">All Statuses</option>
              <option value="COMPLETED">Completed</option>
              <option value="RUNNING">Running</option>
              <option value="PENDING">Pending</option>
              <option value="FAILED">Failed</option>
            </select>
          </div>

          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-50 transition-colors"
            title="Refresh Audits"
          >
            <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin text-emerald-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Main Table Card */}
      <div className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center text-slate-400 text-xs animate-pulse">
            Loading audit runs from database...
          </div>
        ) : error ? (
          <div className="p-8 text-center text-red-400 text-xs">
            Failed to load audits: {(error as Error).message}
          </div>
        ) : filteredAudits.length === 0 ? (
          <div className="p-12 text-center">
            <FileCheck2 className="h-10 w-10 text-slate-600 mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-slate-300">No matching audits found</h3>
            <p className="text-xs text-slate-400 mt-1">
              Try adjusting your search criteria or filter options.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Audit ID</th>
                  <th className="py-3 px-4">Repository</th>
                  <th className="py-3 px-4">PR / Branch</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Trust Score</th>
                  <th className="py-3 px-4">Recommendation</th>
                  <th className="py-3 px-4">Total Findings</th>
                  <th className="py-3 px-4">Started At</th>
                  <th className="py-3 px-4 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300 font-mono">
                {filteredAudits.map((audit) => {
                  const pr = audit.pull_request;
                  const score = audit.trust_score;

                  return (
                    <tr
                      key={audit.id}
                      onClick={() => onSelectAudit(audit.id)}
                      className="hover:bg-slate-800/30 transition-colors cursor-pointer"
                    >
                      <td className="py-3.5 px-4 font-bold text-white">#{audit.id}</td>
                      <td className="py-3.5 px-4 font-sans font-medium text-slate-200">
                        {pr ? pr.repository_full_name : 'Local / CLI Execution'}
                      </td>
                      <td className="py-3.5 px-4">
                        {pr ? (
                          <div className="flex items-center gap-1.5 text-slate-300">
                            <GitPullRequest className="h-3.5 w-3.5 text-slate-400" />
                            <span>#{pr.pr_number}</span>
                            <span className="text-slate-400 text-[11px]">({pr.commit_sha.substring(0, 7)})</span>
                          </div>
                        ) : (
                          <span className="text-slate-400 italic font-sans">-</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                          audit.status === 'COMPLETED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                          audit.status === 'RUNNING' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20 animate-pulse' :
                          audit.status === 'FAILED' ? 'bg-red-500/10 text-red-400 border border-red-500/20' :
                          'bg-slate-800 text-slate-400'
                        }`}>
                          {audit.status}
                        </span>
                      </td>
                      <td className="py-3.5 px-4">
                        {typeof score === 'number' ? (
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
                      <td className="py-3.5 px-4 font-sans font-semibold">
                        {audit.recommendation ? (
                          <span className={`text-[11px] ${
                            audit.recommendation === 'APPROVE' ? 'text-emerald-400' :
                            audit.recommendation === 'REQUEST_CHANGES' ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {audit.recommendation}
                          </span>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4">
                        <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                          {audit.findings?.length || 0}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 font-sans text-[11px] text-slate-400">
                        {new Date(audit.started_at).toLocaleString()}
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectAudit(audit.id);
                          }}
                          className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-emerald-400 font-sans text-xs transition-colors"
                        >
                          View
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
