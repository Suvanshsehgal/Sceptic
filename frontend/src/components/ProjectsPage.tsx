import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FolderGit2, Plus, ExternalLink, GitBranch, Calendar } from 'lucide-react';
import { Project } from '../types';
import { useAuth } from '../context/AuthContext';

export const ProjectsPage: React.FC = () => {
  const { user, token } = useAuth();
  const queryClient = useQueryClient();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [name, setName] = useState('');
  const [repoUrl, setRepoUrl] = useState('');
  const [description, setDescription] = useState('');

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  const { data: projects = [], isLoading } = useQuery<Project[]>({
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

  const createMutation = useMutation({
    mutationFn: async (newProj: { name: string; repository_url: string; description: string }) => {
      const res = await fetch(`${API_URL}/projects`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(newProj),
      });
      if (!res.ok) throw new Error('Failed to create project');
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setShowCreateModal(false);
      setName('');
      setRepoUrl('');
      setDescription('');
    },
  });

  if (!user) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-12 text-center">
        <FolderGit2 className="mx-auto h-12 w-12 text-slate-500 mb-4" />
        <h3 className="text-lg font-bold text-white mb-2">Authentication Required</h3>
        <p className="text-sm text-slate-400 max-w-md mx-auto mb-6">
          Please log in with Google to create and manage your verified code projects.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Your Projects</h2>
          <p className="text-xs text-slate-400">Repositories synchronized across Web Dashboard and Sceptic CLI</p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-xs transition-colors"
        >
          <Plus className="h-4 w-4" />
          <span>New Project</span>
        </button>
      </div>

      {isLoading ? (
        <div className="p-8 text-center text-slate-400 font-mono text-xs">Loading projects...</div>
      ) : projects.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-12 text-center">
          <FolderGit2 className="mx-auto h-12 w-12 text-slate-600 mb-3" />
          <p className="text-sm font-semibold text-white mb-1">No projects registered yet</p>
          <p className="text-xs text-slate-400 max-w-sm mx-auto mb-4">
            Create a project here or run <code className="text-emerald-400 font-mono">sceptic project --create &lt;name&gt;</code> in your terminal.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((proj) => (
            <div
              key={proj.id}
              className="p-5 rounded-xl border border-slate-800 bg-slate-900/60 hover:border-slate-700 transition-all space-y-3"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <FolderGit2 className="h-5 w-5 text-emerald-400" />
                  <h3 className="font-bold text-white text-sm">{proj.name}</h3>
                </div>
                {proj.repository_url && (
                  <a
                    href={proj.repository_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-slate-400 hover:text-white"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                )}
              </div>

              {proj.description && (
                <p className="text-xs text-slate-400 line-clamp-2">{proj.description}</p>
              )}

              <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500">
                <span className="flex items-center gap-1 font-mono">
                  <GitBranch className="h-3 w-3" /> {proj.default_branch || 'main'}
                </span>
                <span className="flex items-center gap-1 font-mono">
                  <Calendar className="h-3 w-3" /> {new Date(proj.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
            <h3 className="text-base font-bold text-white">Create New Project</h3>
            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 mb-1">Project Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. core-auth-service"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white outline-none focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="block text-slate-300 mb-1">Repository URL (optional)</label>
                <input
                  type="text"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  placeholder="https://github.com/org/repo"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white outline-none focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="block text-slate-300 mb-1">Description (optional)</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Brief summary of project scope"
                  rows={2}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white outline-none focus:border-emerald-500"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowCreateModal(false)}
                className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 text-xs"
              >
                Cancel
              </button>
              <button
                disabled={!name.trim() || createMutation.isPending}
                onClick={() => createMutation.mutate({ name, repository_url: repoUrl, description })}
                className="px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-xs disabled:opacity-50"
              >
                {createMutation.isPending ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
