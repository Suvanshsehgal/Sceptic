import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Sparkles, Plus, FolderGit2, Calendar, CheckCircle2, AlertCircle } from 'lucide-react';
import { FeatureAnalysis, Project } from '../types';
import { useAuth } from '../context/AuthContext';

export const FeaturesPage: React.FC = () => {
  const { user, token } = useAuth();
  const queryClient = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [featureDescription, setFeatureDescription] = useState<string>('');
  const [selectedAnalysis, setSelectedAnalysis] = useState<FeatureAnalysis | null>(null);

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  // Fetch user projects
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects', user?.id],
    queryFn: async () => {
      if (!token) return [];
      const res = await fetch(`${API_URL}/projects`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to fetch projects');
      return res.json();
    },
    enabled: !!token,
  });

  const activeProjId = selectedProjectId || (projects.length > 0 ? projects[0].id : '');

  // Fetch analyses for active project
  const { data: analyses = [], isLoading } = useQuery<FeatureAnalysis[]>({
    queryKey: ['feature-analyses', activeProjId],
    queryFn: async () => {
      if (!token || !activeProjId) return [];
      const res = await fetch(`${API_URL}/projects/${activeProjId}/feature-analyses`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to fetch feature analyses');
      return res.json();
    },
    enabled: !!token && !!activeProjId,
  });

  const analyzeMutation = useMutation({
    mutationFn: async ({ projId, desc }: { projId: string; desc: string }) => {
      const res = await fetch(`${API_URL}/projects/${projId}/feature-analyses`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ feature_description: desc }),
      });
      if (!res.ok) throw new Error('Feature evaluation failed');
      return res.json();
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['feature-analyses', activeProjId] });
      setFeatureDescription('');
      setSelectedAnalysis(data);
    },
  });

  if (!user) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-12 text-center">
        <Sparkles className="mx-auto h-12 w-12 text-slate-500 mb-4" />
        <h3 className="text-lg font-bold text-white mb-2">Authentication Required</h3>
        <p className="text-sm text-slate-400 max-w-md mx-auto">
          Please log in with Google to evaluate architecture feasibility and generate feature implementation plans.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-emerald-400" />
            <span>Feature Architecture & Feasibility Analysis</span>
          </h2>
          <p className="text-xs text-slate-400">Pre-implementation technical scoping, risk modeling, and roadmap synthesis</p>
        </div>

        {projects.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Project:</span>
            <select
              value={activeProjId}
              onChange={(e) => {
                setSelectedProjectId(e.target.value);
                setSelectedAnalysis(null);
              }}
              className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white outline-none focus:border-emerald-500"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Analysis Input Box */}
      <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
        <label className="block text-xs font-semibold text-slate-300">
          Propose New Feature or Architecture Change
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={featureDescription}
            onChange={(e) => setFeatureDescription(e.target.value)}
            placeholder="e.g. Implement Google OAuth with shared CLI session token storage"
            className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-xs text-white outline-none focus:border-emerald-500"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && featureDescription.trim() && activeProjId) {
                analyzeMutation.mutate({ projId: activeProjId, desc: featureDescription });
              }
            }}
          />
          <button
            disabled={!featureDescription.trim() || !activeProjId || analyzeMutation.isPending}
            onClick={() => analyzeMutation.mutate({ projId: activeProjId, desc: featureDescription })}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-xs disabled:opacity-50 transition-colors"
          >
            <Sparkles className="h-3.5 w-3.5" />
            <span>{analyzeMutation.isPending ? 'Scoping...' : 'Evaluate Feature'}</span>
          </button>
        </div>
        <p className="text-[11px] text-slate-500">
          Tip: You can also evaluate features directly in terminal via <code className="text-emerald-400 font-mono">sceptic newfeature "&lt;description&gt;"</code>.
        </p>
      </div>

      {/* Active Analysis Detail */}
      {selectedAnalysis && (
        <div className="p-6 rounded-xl border border-emerald-500/30 bg-emerald-500/5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-white text-base">{selectedAnalysis.feature_description}</h3>
            <span className="text-xs font-mono text-emerald-400">Scored by Sceptic Engine</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 text-center">
              <span className="text-[11px] text-slate-400">Feasibility</span>
              <p className="text-lg font-bold text-emerald-400">{selectedAnalysis.feasibility_score.toFixed(1)}%</p>
            </div>
            <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 text-center">
              <span className="text-[11px] text-slate-400">Complexity</span>
              <p className="text-lg font-bold text-yellow-400">{selectedAnalysis.complexity_score.toFixed(1)}%</p>
            </div>
            <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 text-center">
              <span className="text-[11px] text-slate-400">Risk</span>
              <p className="text-lg font-bold text-emerald-400">{selectedAnalysis.risk_score.toFixed(1)}%</p>
            </div>
            <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 text-center">
              <span className="text-[11px] text-slate-400">Confidence</span>
              <p className="text-lg font-bold text-cyan-400">{selectedAnalysis.confidence_score.toFixed(1)}%</p>
            </div>
          </div>

          <div className="space-y-2">
            <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">Implementation Plan</h4>
            <div className="p-4 rounded-lg bg-slate-950 border border-slate-800 font-mono text-xs text-slate-300 whitespace-pre-line leading-relaxed">
              {selectedAnalysis.implementation_plan}
            </div>
          </div>
        </div>
      )}

      {/* Historical Analyses List */}
      <div className="space-y-3">
        <h3 className="text-sm font-bold text-white">Project Evaluation History</h3>
        {isLoading ? (
          <div className="text-xs text-slate-400 font-mono">Loading analyses...</div>
        ) : analyses.length === 0 ? (
          <div className="p-8 text-center border border-slate-800 rounded-xl bg-slate-900/40 text-xs text-slate-500">
            No feature analyses recorded yet for this project.
          </div>
        ) : (
          <div className="divide-y divide-slate-800 rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
            {analyses.map((item) => (
              <div
                key={item.id}
                onClick={() => setSelectedAnalysis(item)}
                className="p-4 flex items-center justify-between hover:bg-slate-800/40 cursor-pointer transition-colors"
              >
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-white">{item.feature_description}</p>
                  <p className="text-[11px] text-slate-400 font-mono flex items-center gap-2">
                    <Calendar className="h-3 w-3" /> {new Date(item.created_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex items-center gap-4 text-xs font-mono">
                  <span className="text-emerald-400 font-bold">{item.feasibility_score.toFixed(0)}% Feasible</span>
                  <span className="text-yellow-400">{item.complexity_score.toFixed(0)}% Complexity</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
