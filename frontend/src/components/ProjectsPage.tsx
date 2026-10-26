import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FolderGit2, Plus, ExternalLink, GitBranch, Calendar } from 'lucide-react';
import { Project } from '../types';
import { useAuth } from '../context/AuthContext';
import { Button, Card, EmptyState, ErrorBanner, Field, PageHeader, Skeleton, fieldClass } from './ui';

export const ProjectsPage: React.FC = () => {
  const { user, token } = useAuth();
  const queryClient = useQueryClient();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [name, setName] = useState('');
  const [repoUrl, setRepoUrl] = useState('');
  const [description, setDescription] = useState('');

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  const { data: projects = [], isLoading, error } = useQuery<Project[]>({
    queryKey: ['projects', user?.id],
    queryFn: async () => {
      if (!token) return [];
      const res = await fetch(`${API_URL}/projects`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Could not load projects. Try signing in again.');
      return res.json();
    },
    enabled: !!token,
  });

  const createMutation = useMutation({
    mutationFn: async (newProj: { name: string; repository_url: string; description: string }) => {
      const res = await fetch(`${API_URL}/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(newProj),
      });
      if (!res.ok) throw new Error('The project could not be created. Check the name and try again.');
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
      <EmptyState
        icon={<FolderGit2 className="h-12 w-12" />}
        title="Sign in to manage projects"
        description="Projects group your audits, deployments, and feature analyses. They are private to your account."
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Projects"
        description="Repositories synchronized between the web dashboard and the Sceptic CLI."
        actions={
          <Button variant="primary" onClick={() => setShowCreateModal(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            New project
          </Button>
        }
      />

      {error ? (
        <ErrorBanner title="Projects unavailable" message={(error as Error).message} />
      ) : isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-36" />)}
        </div>
      ) : projects.length === 0 ? (
        <Card>
          <EmptyState
            icon={<FolderGit2 className="h-12 w-12" />}
            title="No projects yet"
            description="Create a project, or run `sceptic project --create <name>` in a terminal."
            action={<Button variant="primary" onClick={() => setShowCreateModal(true)}>Create a project</Button>}
          />
        </Card>
      ) : (
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((proj) => (
            <li key={proj.id}>
              <Card className="h-full transition-colors hover:border-line-strong">
                <div className="flex h-full flex-col gap-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <FolderGit2 className="h-5 w-5 shrink-0 text-accent" aria-hidden />
                      <h2 className="truncate text-sm font-semibold text-ink">{proj.name}</h2>
                    </div>
                    {proj.repository_url && (
                      <a
                        href={proj.repository_url}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`Open ${proj.name} repository in a new tab`}
                        className="rounded-md p-1 text-ink-muted hover:text-ink"
                      >
                        <ExternalLink className="h-4 w-4" aria-hidden />
                      </a>
                    )}
                  </div>
                  {proj.description ? (
                    <p className="line-clamp-2 text-xs leading-relaxed text-ink-muted">{proj.description}</p>
                  ) : (
                    <p className="text-xs text-ink-subtle">No description</p>
                  )}
                  <div className="mt-auto flex items-center justify-between border-t border-line pt-3 font-mono text-[11px] text-ink-subtle">
                    <span className="flex items-center gap-1.5">
                      <GitBranch className="h-3 w-3" aria-hidden /> {proj.default_branch || 'main'}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <Calendar className="h-3 w-3" aria-hidden /> {new Date(proj.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-project-title"
            className="w-full max-w-md space-y-5 rounded-2xl border border-line bg-surface p-6 shadow-2xl"
            onKeyDown={(e) => {
              if (e.key === 'Escape') setShowCreateModal(false);
            }}
          >
            <div>
              <h2 id="create-project-title" className="text-base font-semibold text-ink">Create a project</h2>
              <p className="mt-1 text-xs text-ink-muted">Audits, deployments, and feature analyses are grouped under a project.</p>
            </div>
            <div className="space-y-4">
              <Field label="Project name" htmlFor="project-name" hint="Required. Use a short, unique name.">
                <input
                  id="project-name"
                  type="text"
                  value={name}
                  autoFocus
                  onChange={(e) => setName(e.target.value)}
                  placeholder="core-auth-service"
                  className={fieldClass}
                />
              </Field>
              <Field label="Repository URL" htmlFor="project-repo" hint="Optional.">
                <input
                  id="project-repo"
                  type="url"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  placeholder="https://github.com/org/repo"
                  className={fieldClass}
                />
              </Field>
              <Field label="Description" htmlFor="project-description" hint="Optional.">
                <textarea
                  id="project-description"
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What this project covers"
                  className={fieldClass}
                />
              </Field>
            </div>
            {createMutation.isError && (
              <p role="alert" className="text-xs text-danger">{(createMutation.error as Error).message}</p>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={() => setShowCreateModal(false)}>Cancel</Button>
              <Button
                variant="primary"
                disabled={!name.trim() || createMutation.isPending}
                onClick={() => createMutation.mutate({ name: name.trim(), repository_url: repoUrl, description })}
              >
                {createMutation.isPending ? 'Creating' : 'Create project'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
