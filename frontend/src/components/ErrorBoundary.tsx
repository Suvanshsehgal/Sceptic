import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error caught by ErrorBoundary:', error, errorInfo);
  }

  public handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-canvas flex items-center justify-center p-6">
          <div className="max-w-lg w-full bg-surface border border-red-800/60 rounded-2xl p-6 shadow-2xl text-ink">
            <div className="flex items-center gap-3 text-danger mb-4">
              <AlertTriangle className="h-6 w-6 shrink-0" />
              <h2 className="text-lg font-bold">Something went wrong</h2>
            </div>
            <p className="text-xs text-ink-muted mb-4 leading-relaxed">
              An error occurred while rendering the interface. The details below may help identify the issue:
            </p>
            <div className="p-3 bg-canvas rounded-lg border border-line font-mono text-[11px] text-danger overflow-x-auto mb-6 whitespace-pre-wrap">
              {this.state.error?.message || 'Unknown runtime error'}
            </div>
            <div className="flex gap-3">
              <button
                onClick={this.handleReset}
                className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent-strong text-accent-ink font-semibold text-xs rounded-lg transition-colors"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                <span>Reload Page</span>
              </button>
              <button
                onClick={() => this.setState({ hasError: false, error: null })}
                className="px-4 py-2 bg-surface-raised hover:bg-slate-700 text-ink font-medium text-xs rounded-lg transition-colors"
              >
                Try Again
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
