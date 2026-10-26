import React from 'react';
import { AlertTriangle, CheckCircle2, CircleDashed, Info, XCircle } from 'lucide-react';

/* ---------- Buttons ---------- */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md';

const buttonBase =
  'inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors ' +
  'disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-offset-2';

const buttonVariants: Record<ButtonVariant, string> = {
  primary: 'bg-action text-action-ink hover:bg-white',
  secondary: 'border border-line-strong bg-transparent text-ink hover:bg-surface-raised',
  ghost: 'text-ink-muted hover:bg-surface-raised hover:text-ink',
  danger: 'border border-danger/40 text-danger hover:bg-danger/10',
};

const buttonSizes: Record<ButtonSize, string> = {
  sm: 'h-7 px-2.5 text-xs',
  md: 'h-9 px-3.5 text-sm',
};

export function Button({
  variant = 'secondary',
  size = 'md',
  className = '',
  type = 'button',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return (
    <button
      type={type}
      className={`${buttonBase} ${buttonVariants[variant]} ${buttonSizes[size]} ${className}`}
      {...props}
    />
  );
}

/* ---------- Form fields ---------- */

export const fieldClass =
  'w-full rounded-md border border-line-strong bg-canvas px-3 py-2 text-sm text-ink placeholder:text-ink-subtle ' +
  'transition-colors focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-50';

export function Field({ label, hint, htmlFor, children }: {
  label: string;
  hint?: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink-muted">{label}</label>
      {children}
      {hint && <p className="text-xs text-ink-subtle">{hint}</p>}
    </div>
  );
}

/* ---------- Surfaces ---------- */

export function Card({ title, description, actions, children, className = '', padded = true }: {
  title?: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={`rounded-lg border border-line bg-surface ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-medium text-ink">{title}</h2>}
            {description && <p className="mt-0.5 text-[13px] text-ink-subtle">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? 'p-5' : ''}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold leading-tight tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ---------- Status ---------- */

export type Tone = 'success' | 'warning' | 'danger' | 'critical' | 'info' | 'neutral';

const toneText: Record<Tone, string> = {
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  critical: 'text-critical',
  info: 'text-info',
  neutral: 'text-ink-muted',
};

const toneDot: Record<Tone, string> = {
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  critical: 'bg-critical',
  info: 'bg-info',
  neutral: 'bg-ink-subtle',
};

/* A status is a colored dot and a word. No boxes, so tables stay calm. */
export function Badge({ tone = 'neutral', children, icon }: {
  tone?: Tone;
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium ${toneText[tone]}`}>
      {icon ?? <span className={`h-1.5 w-1.5 rounded-full ${toneDot[tone]}`} aria-hidden />}
      {children}
    </span>
  );
}

const SEVERITY_TONE: Record<string, Tone> = {
  CRITICAL: 'critical',
  HIGH: 'danger',
  MEDIUM: 'warning',
  LOW: 'info',
  INFO: 'neutral',
};

export function SeverityBadge({ severity }: { severity: string }) {
  const key = (severity || 'INFO').toUpperCase();
  return <Badge tone={SEVERITY_TONE[key] ?? 'neutral'}>{key.charAt(0) + key.slice(1).toLowerCase()}</Badge>;
}

const STATUS_STYLE: Record<string, { tone: Tone; label: string; icon: React.ReactNode }> = {
  COMPLETED: { tone: 'success', label: 'Completed', icon: <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> },
  ACTIVE: { tone: 'success', label: 'Active', icon: <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> },
  RUNNING: { tone: 'info', label: 'Running', icon: <CircleDashed className="h-3.5 w-3.5 animate-spin" aria-hidden /> },
  DEPLOYING: { tone: 'info', label: 'Deploying', icon: <CircleDashed className="h-3.5 w-3.5 animate-spin" aria-hidden /> },
  QUEUED: { tone: 'neutral', label: 'Queued', icon: <CircleDashed className="h-3.5 w-3.5" aria-hidden /> },
  PENDING: { tone: 'neutral', label: 'Pending', icon: <CircleDashed className="h-3.5 w-3.5" aria-hidden /> },
  FAILED: { tone: 'danger', label: 'Failed', icon: <XCircle className="h-3.5 w-3.5" aria-hidden /> },
  ROLLED_BACK: { tone: 'warning', label: 'Rolled back', icon: <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> },
};

export function StatusBadge({ status }: { status: string }) {
  const key = (status || 'PENDING').toUpperCase();
  const style = STATUS_STYLE[key] ?? { tone: 'neutral' as Tone, label: key, icon: null };
  return <Badge tone={style.tone} icon={style.icon}>{style.label}</Badge>;
}

export function trustTone(score: number | null | undefined): Tone {
  if (typeof score !== 'number') return 'neutral';
  if (score >= 85) return 'success';
  if (score >= 65) return 'warning';
  return 'danger';
}

export function RecommendationBadge({ value }: { value?: string | null }) {
  if (!value) return <span className="text-sm text-ink-subtle">No verdict</span>;
  const tone: Tone = value === 'APPROVE' ? 'success' : value === 'REQUEST_CHANGES' ? 'warning' : 'danger';
  return <Badge tone={tone}>{value === 'REQUEST_CHANGES' ? 'Request changes' : value === 'APPROVE' ? 'Approve' : 'Block'}</Badge>;
}

/* ---------- Metrics ---------- */

export function StatCard({ label, value, hint, tone = 'neutral' }: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: Tone;
  icon?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-5">
      <div className="text-[13px] text-ink-muted">{label}</div>
      <div className={`tabular mt-2 font-mono text-[28px] font-medium leading-none ${tone === 'neutral' ? 'text-ink' : toneText[tone]}`}>
        {value}
      </div>
      {hint && <div className="mt-2 text-xs text-ink-subtle">{hint}</div>}
    </div>
  );
}

/* ---------- States ---------- */

export function EmptyState({ icon, title, description, action }: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      {icon && <div className="mb-4 text-ink-subtle" aria-hidden>{icon}</div>}
      <h3 className="text-sm font-medium text-ink">{title}</h3>
      {description && <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-ink-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton rounded-md ${className}`} aria-hidden />;
}

export function ErrorBanner({ title, message, action }: {
  title: string;
  message?: string;
  action?: React.ReactNode;
}) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-danger/25 bg-danger/5 p-4">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{title}</p>
        {message && <p className="mt-0.5 break-words text-[13px] text-ink-muted">{message}</p>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}

export function InfoNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 rounded-md border border-line bg-surface-raised p-3 text-[13px] text-ink-muted">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
      <div>{children}</div>
    </div>
  );
}

/* ---------- Tables ---------- */

export const tableClasses = {
  wrap: 'overflow-x-auto',
  table: 'w-full min-w-[640px] text-left text-sm',
  head: 'border-b border-line text-[13px] font-medium text-ink-subtle',
  th: 'px-5 py-2.5 font-medium',
  row: 'border-b border-line last:border-0 transition-colors hover:bg-white/[0.02]',
  td: 'px-5 py-3 align-middle text-ink',
  mono: 'font-mono text-[13px] text-ink-muted tabular',
};
