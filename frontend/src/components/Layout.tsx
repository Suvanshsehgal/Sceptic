import React, { useEffect, useState } from 'react';
import {
  LayoutDashboard,
  FolderGit2,
  FileCheck2,
  Sparkles,
  AlertTriangle,
  Rocket,
  BookOpen,
  Menu,
  X,
  LogOut,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import { AuthModal } from './AuthModal';
import { fetchHealth } from '../api';
import { Button } from './ui';

interface NavItem {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  { title: '', items: [{ id: 'dashboard', label: 'Overview', icon: LayoutDashboard }] },
  {
    title: 'Verification',
    items: [
      { id: 'audits', label: 'Audits', icon: FileCheck2 },
      { id: 'findings', label: 'Findings', icon: AlertTriangle },
      { id: 'features', label: 'Feature analysis', icon: Sparkles },
    ],
  },
  {
    title: 'Operations',
    items: [
      { id: 'projects', label: 'Projects', icon: FolderGit2 },
      { id: 'deployments', label: 'Deployments', icon: Rocket },
    ],
  },
  { title: '', items: [{ id: 'docs', label: 'Documentation', icon: BookOpen }] },
];

interface SidebarProps {
  currentTab: string;
  onSelectTab: (tab: string) => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentTab, onSelectTab, mobileOpen, onCloseMobile }) => {
  const { user, logout } = useAuth();
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseMobile();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mobileOpen, onCloseMobile]);

  const openAuth = (mode: 'login' | 'register') => {
    setAuthMode(mode);
    setAuthModalOpen(true);
  };

  return (
    <>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-black/50 lg:hidden" onClick={onCloseMobile} aria-hidden />
      )}

      <aside
        id="site-nav"
        aria-label="Primary"
        className={`fixed inset-y-0 left-0 z-50 flex w-60 flex-col border-r border-line bg-canvas transition-transform duration-200 ease-out lg:translate-x-0 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex h-14 items-center justify-between px-5">
          <div className="flex items-center gap-2.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-accent" aria-hidden />
            <span className="text-sm font-semibold tracking-tight text-ink">Sceptic</span>
          </div>
          <button
            type="button"
            onClick={onCloseMobile}
            aria-label="Close navigation"
            className="rounded-md p-1.5 text-ink-muted hover:bg-surface-raised hover:text-ink lg:hidden"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>

        <nav className="flex-1 space-y-6 overflow-y-auto px-3 pb-6 pt-2">
          {NAV_SECTIONS.map((section, index) => (
            <div key={section.title || `group-${index}`}>
              {section.title && (
                <p className="px-2.5 pb-1.5 text-xs font-medium text-ink-subtle">{section.title}</p>
              )}
              <ul className="space-y-px">
                {section.items.map((item) => {
                  const Icon = item.icon;
                  const active = currentTab === item.id;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        aria-current={active ? 'page' : undefined}
                        onClick={() => {
                          onSelectTab(item.id);
                          onCloseMobile();
                        }}
                        className={`relative flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors ${
                          active
                            ? 'bg-surface-raised font-medium text-ink'
                            : 'text-ink-muted hover:bg-surface hover:text-ink'
                        }`}
                      >
                        {active && <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent" aria-hidden />}
                        <Icon className={`h-4 w-4 ${active ? 'text-ink' : 'text-ink-subtle'}`} aria-hidden />
                        {item.label}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-line p-3">
          {user ? (
            <div className="flex items-center gap-3 rounded-md px-2 py-2">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-raised text-xs font-medium text-ink-muted">
                {user.avatar_url ? (
                  <img src={user.avatar_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  user.name.charAt(0).toUpperCase()
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium text-ink">{user.name}</p>
                <p className="truncate text-xs text-ink-subtle">{user.email}</p>
              </div>
              <button
                type="button"
                onClick={logout}
                aria-label="Sign out"
                title="Sign out"
                className="rounded-md p-1.5 text-ink-subtle hover:bg-surface-raised hover:text-ink"
              >
                <LogOut className="h-4 w-4" aria-hidden />
              </button>
            </div>
          ) : (
            <div className="space-y-2 p-1">
              <Button variant="primary" className="w-full" onClick={() => openAuth('login')}>
                Sign in
              </Button>
              <div className="flex items-center justify-center gap-3 text-xs text-ink-subtle">
                <button type="button" onClick={() => openAuth('register')} className="hover:text-ink">
                  Create account
                </button>
                <span aria-hidden>·</span>
                <button
                  type="button"
                  onClick={() => {
                    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
                    window.location.href = `${API_URL}/auth/google/login`;
                  }}
                  className="hover:text-ink"
                >
                  Google
                </button>
              </div>
            </div>
          )}
        </div>
      </aside>

      <AuthModal isOpen={authModalOpen} onClose={() => setAuthModalOpen(false)} initialMode={authMode} />
    </>
  );
};

export const Header: React.FC<{
  onOpenMobile: () => void;
  title: string;
  subtitle?: string;
}> = ({ onOpenMobile, title, subtitle }) => {
  const { data: health, isError, isLoading } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 10000,
  });

  const engine = isLoading
    ? { label: 'Connecting', dot: 'bg-warning', text: 'text-ink-muted' }
    : isError || !health
      ? { label: 'Engine offline', dot: 'bg-danger', text: 'text-danger' }
      : { label: 'Engine online', dot: 'bg-success', text: 'text-ink-muted' };

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-4 border-b border-line bg-canvas/90 px-4 backdrop-blur sm:px-8">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onOpenMobile}
          aria-label="Open navigation"
          aria-controls="site-nav"
          className="rounded-md p-1.5 text-ink-muted hover:bg-surface-raised hover:text-ink lg:hidden"
        >
          <Menu className="h-5 w-5" aria-hidden />
        </button>
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2 text-[13px]">
          <span className="text-ink-subtle">Sceptic</span>
          <span className="text-ink-subtle" aria-hidden>/</span>
          <span className="truncate text-ink" aria-current="page" title={subtitle}>{title}</span>
        </nav>
      </div>
      <div role="status" aria-live="polite" className={`flex shrink-0 items-center gap-2 text-xs ${engine.text}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${engine.dot} ${isLoading ? 'animate-pulse' : ''}`} aria-hidden />
        {engine.label}
      </div>
    </header>
  );
};
