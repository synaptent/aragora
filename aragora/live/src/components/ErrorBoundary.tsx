'use client';

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { getCrashReporter } from '@/lib/crash-reporter';

interface Props {
  children: ReactNode;
  /** Custom fallback renderer */
  fallback?: (error: Error, resetError: () => void) => ReactNode;
  /** Human-readable name of the wrapped component (shown in the fallback UI) */
  componentName?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  reported: boolean;
}

/**
 * React Error Boundary component for catching render errors.
 *
 * Prevents the entire app from crashing when a component throws an error.
 * Displays a terminal-styled error UI with reset functionality and
 * automatically reports the crash to the backend via CrashReporter.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, reported: false };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught error:', error, errorInfo);

    // Report to crash telemetry
    const reporter = getCrashReporter();
    const accepted = reporter.capture(error, {
      componentStack: errorInfo.componentStack ?? null,
      componentName: this.props.componentName ?? null,
    });

    this.setState({ reported: accepted });
  }

  resetError = () => {
    this.setState({ hasError: false, error: null, reported: false });
  };

  handleReport = () => {
    if (!this.state.error) return;
    const reporter = getCrashReporter();
    // Force-flush any queued reports (including this one)
    reporter.flush();
    this.setState({ reported: true });
  };

  render() {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.resetError);
      }

      const displayName = this.props.componentName || 'Component';

      // Terminal-styled default error UI
      return (
        <div className="min-h-screen bg-bg flex items-center justify-center p-4">
          <div className="max-w-2xl w-full border border-[var(--crimson)] bg-surface p-6 font-theme-data">
            <div className="flex items-start gap-3 mb-4">
              <div className="text-[var(--crimson)] text-2xl">{'>'}</div>
              <div>
                <div className="text-[var(--crimson)] font-bold mb-2">RUNTIME ERROR</div>
                <div className="text-warning text-sm mb-4">{displayName} crashed during render</div>
              </div>
            </div>

            <div className="bg-bg border border-border p-3 mb-4 text-text-muted text-xs overflow-x-auto">
              <div className="mb-2 text-text">
                {'>'} {this.state.error.name}
              </div>
              <div className="pl-4 text-[var(--crimson)]">{this.state.error.message}</div>
              {this.state.error.stack && (
                <div className="mt-3 pl-4 text-text-muted text-[10px] font-normal opacity-70 whitespace-pre-wrap">
                  {this.state.error.stack.split('\n').slice(1, 6).join('\n')}
                </div>
              )}
            </div>

            <div className="flex gap-3">
              <button
                onClick={this.resetError}
                className="flex-1 border border-accent text-accent py-2 px-4 hover:bg-accent hover:text-bg transition-colors font-bold"
              >
                {'>'} RESET_COMPONENT
              </button>

              <button
                onClick={this.handleReport}
                disabled={this.state.reported}
                className={`flex-1 border py-2 px-4 transition-colors font-bold ${
                  this.state.reported
                    ? 'border-text-muted text-text-muted cursor-not-allowed opacity-50'
                    : 'border-warning text-warning hover:bg-warning hover:text-bg'
                }`}
              >
                {this.state.reported ? '> REPORTED' : '> REPORT_ERROR'}
              </button>
            </div>

            <div className="mt-4 text-text-muted text-xs text-center">
              {this.state.reported
                ? 'Error report sent. If the issue persists, try resetting.'
                : 'Click REPORT_ERROR to send crash details to our team.'}
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
