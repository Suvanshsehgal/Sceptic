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
        <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
          <div className="max-w-lg w-full bg-slate-900 border border-red-800/60 rounded-2xl p-6 shadow-2xl text-slate-200">
            <div className="flex items-center gap-3 text-red-400 mb-4">
              <AlertTriangle className="h-6 w-6 shrink-0" />
              <h2 className="text-lg font-bold">Something went wrong</h2>
            </div>
            <p className="text-xs text-slate-400 mb-4 leading-relaxed">
              An error occurred while rendering the interface. The details below may help identify the issue:
            </p>
            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 font-mono text-[11px] text-red-300 overflow-x-auto mb-6 whitespace-pre-wrap">
              {this.state.error?.message || 'Unknown runtime error'}
            </div>
            <div className="flex gap-3">
              <button
                onClick={this.handleReset}
                className="flex items-center gap-2 px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-xs rounded-lg transition-colors"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                <span>Reload Page</span>
              </button>
              <button
                onClick={() => this.setState({ hasError: false, error: null })}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium text-xs rounded-lg transition-colors"
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
