'use client';

import { useEffect, useMemo } from 'react';
import Link from 'next/link';
import { getCrashReporter } from '@/lib/crash-reporter';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const timestamp = useMemo(() => new Date().toISOString(), []);

  useEffect(() => {
    console.error('App error:', error);
    if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
      void import('@sentry/nextjs')
        .then((Sentry) => Sentry.captureException(error))
        .catch(() => {
          // Keep the recovery UI usable even if the optional SDK cannot load.
        });
    }
    const reporter = getCrashReporter();
    const accepted = reporter.capture(error, { componentName: 'next-app-error-boundary' });
    if (accepted) {
      reporter.flush();
    }
  }, [error]);

  const isHydrationError =
    error.message?.includes('Hydration') ||
    error.message?.includes('hydrat') ||
    error.message?.includes('server-rendered') ||
    error.message?.includes('Text content does not match') ||
    error.digest?.includes('NEXT_');

  const handleHardRefresh = () => {
    if (typeof window !== 'undefined') {
      window.location.reload();
    }
  };

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-4">
      <div className="max-w-md w-full border border-[var(--crimson)] bg-surface p-6 font-theme-data">
        <div className="text-center mb-6">
          <div className="text-[var(--crimson)] text-4xl mb-3">!</div>
          <h1 className="text-[var(--crimson)] font-bold text-lg mb-2">SOMETHING WENT WRONG</h1>
          <p className="text-text-muted text-sm">
            {isHydrationError
              ? 'A temporary rendering issue occurred. Refreshing usually fixes this.'
              : 'An unexpected error occurred. Please try again.'}
          </p>
        </div>

        <div className="flex gap-3 mb-4">
          <button
            onClick={reset}
            className="flex-1 border border-[var(--accent)] text-[var(--accent)] py-2 px-4 hover:bg-[var(--accent)] hover:text-bg transition-colors font-bold text-sm"
          >
            RETRY
          </button>
          <button
            onClick={handleHardRefresh}
            className="flex-1 border border-[var(--acid-cyan)] text-[var(--acid-cyan)] py-2 px-4 hover:bg-acid-cyan hover:text-bg transition-colors font-bold text-sm"
          >
            REFRESH PAGE
          </button>
        </div>

        <Link
          href="/"
          className="block w-full border border-text-muted text-text-muted py-2 px-4 hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors text-center text-sm mb-4"
        >
          GO HOME
        </Link>

        {/* Minimal diagnostics — collapsed by default */}
        <details className="text-left">
          <summary className="text-xs font-theme-data text-text-muted/50 cursor-pointer hover:text-text-muted">
            Technical details
          </summary>
          <pre className="mt-2 p-2 bg-bg border border-border text-xs text-text-muted/40 overflow-auto max-h-24 whitespace-pre-wrap break-all">
            {error.message || 'Unknown error'}
            {error.digest ? `\nID: ${error.digest}` : ''}
            {`\n${timestamp}`}
          </pre>
        </details>
      </div>
    </div>
  );
}
