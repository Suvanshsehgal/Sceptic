import React, { useEffect, useId, useRef, useState } from 'react';
import { X, Lock, Mail, User as UserIcon, AlertCircle, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Button, fieldClass } from './ui';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialMode?: 'login' | 'register';
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, initialMode = 'login' }) => {
  const { loginWithCredentials, registerWithCredentials, loginWithMock } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>(initialMode);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  // Refs keep the latest callback and submit state without re-running the open effect on every parent render.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const submittingRef = useRef(false);
  submittingRef.current = submitting;

  useEffect(() => {
    if (!isOpen) return;
    setMode(initialMode);
    setError(null);
    firstFieldRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !submittingRef.current) onCloseRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, initialMode]);

  if (!isOpen) return null;

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
  const isLogin = mode === 'login';

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!isLogin && !name.trim()) {
      setError('Enter your full name to create an account.');
      return;
    }
    setSubmitting(true);
    try {
      const result = isLogin
        ? await loginWithCredentials(email, password)
        : await registerWithCredentials(name.trim(), email, password);
      if (result.success) {
        onClose();
      } else {
        setError(result.error || (isLogin ? 'Sign-in failed. Check your email and password.' : 'Registration failed.'));
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full max-w-md overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-4 top-4 rounded-lg p-1.5 text-ink-muted hover:bg-surface-raised hover:text-ink"
        >
          <X className="h-5 w-5" aria-hidden />
        </button>

        <div className="border-b border-line px-6 pb-5 pt-6 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl border border-accent/30 bg-accent/10 text-accent">
            <Lock className="h-5 w-5" aria-hidden />
          </div>
          <h2 id={titleId} className="text-lg font-semibold text-ink">
            {isLogin ? 'Sign in to Sceptic' : 'Create your account'}
          </h2>
          <p className="mt-1 text-xs text-ink-muted">Independent verification for AI-generated code</p>

          <div className="mt-4 grid grid-cols-2 rounded-lg border border-line bg-canvas p-1" role="tablist" aria-label="Account action">
            {(['login', 'register'] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={mode === tab}
                onClick={() => {
                  setMode(tab);
                  setError(null);
                }}
                className={`rounded-md py-1.5 text-xs font-semibold transition-colors ${
                  mode === tab ? 'bg-surface-raised text-ink shadow-sm' : 'text-ink-muted hover:text-ink'
                }`}
              >
                {tab === 'login' ? 'Sign in' : 'Register'}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-5 p-6">
          {error && (
            <div role="alert" className="flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger/10 p-3 text-xs text-danger">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>{error}</span>
            </div>
          )}

          <Button
            variant="secondary"
            className="w-full"
            onClick={() => {
              window.location.href = `${API_URL}/auth/google/login`;
            }}
          >
            Continue with Google
          </Button>

          <div className="relative flex items-center">
            <div className="w-full border-t border-line" aria-hidden />
            <span className="absolute left-1/2 -translate-x-1/2 bg-surface px-3 text-[11px] uppercase tracking-wider text-ink-subtle">
              or with email
            </span>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {!isLogin && (
              <div className="space-y-1.5">
                <label htmlFor="auth-name" className="block text-xs font-medium text-ink-muted">Full name</label>
                <div className="relative">
                  <UserIcon className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-subtle" aria-hidden />
                  <input
                    id="auth-name"
                    ref={firstFieldRef}
                    type="text"
                    autoComplete="name"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Jane Developer"
                    className={`${fieldClass} pl-9`}
                  />
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <label htmlFor="auth-email" className="block text-xs font-medium text-ink-muted">Email address</label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-subtle" aria-hidden />
                <input
                  id="auth-email"
                  ref={isLogin ? firstFieldRef : undefined}
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="developer@example.com"
                  className={`${fieldClass} pl-9`}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label htmlFor="auth-password" className="block text-xs font-medium text-ink-muted">Password</label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-subtle" aria-hidden />
                <input
                  id="auth-password"
                  type="password"
                  autoComplete={isLogin ? 'current-password' : 'new-password'}
                  required
                  minLength={isLogin ? undefined : 6}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className={`${fieldClass} pl-9`}
                />
              </div>
              {!isLogin && <p className="text-xs text-ink-subtle">At least 6 characters.</p>}
            </div>

            <Button type="submit" variant="primary" className="w-full" disabled={submitting}>
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  {isLogin ? 'Signing in' : 'Creating account'}
                </>
              ) : isLogin ? (
                'Sign in'
              ) : (
                'Create account'
              )}
            </Button>
          </form>

          <div className="border-t border-line pt-4 text-center">
            <button
              type="button"
              onClick={async () => {
                setSubmitting(true);
                try {
                  await loginWithMock('dev@sceptic.dev', 'Demo Developer');
                  onClose();
                } finally {
                  setSubmitting(false);
                }
              }}
              className="text-xs text-ink-muted underline underline-offset-4 hover:text-accent"
            >
              Use the development demo account
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
