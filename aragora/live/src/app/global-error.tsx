'use client';

import { useEffect, useMemo, useState } from 'react';
import { getCrashReporter } from '@/lib/crash-reporter';

/**
 * Global error page for root layout errors
 *
 * This catches errors that occur in the root layout itself.
 * It must provide its own <html> and <body> tags since the root layout may have failed.
 *
 * Includes CRT scanline aesthetic and full diagnostic panel since the normal
 * error.tsx cannot catch root layout failures.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [showStack, setShowStack] = useState(false);
  const timestamp = useMemo(() => new Date().toISOString(), []);

  useEffect(() => {
    console.error('Global app error:', error);
    const reporter = getCrashReporter();
    const accepted = reporter.capture(error, { componentName: 'next-global-error-boundary' });
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
    <html lang="en" className="dark">
      <body
        className="bg-[#0a0a0a] text-[#e0e0e0]"
        style={{ fontFamily: 'JetBrains Mono, monospace' }}
      >
        {/* CRT scanline overlay */}
        <div
          style={{
            position: 'fixed',
            inset: 0,
            pointerEvents: 'none',
            zIndex: 9999,
            background: `repeating-linear-gradient(
              0deg,
              rgba(0, 0, 0, 0.03),
              rgba(0, 0, 0, 0.03) 1px,
              transparent 1px,
              transparent 2px
            )`,
          }}
        />
        {/* CRT vignette */}
        <div
          style={{
            position: 'fixed',
            inset: 0,
            pointerEvents: 'none',
            zIndex: 9998,
            background: `radial-gradient(
              ellipse at center,
              transparent 0%,
              transparent 60%,
              rgba(0, 0, 0, 0.15) 100%
            )`,
          }}
        />

        <div
          className="min-h-screen flex items-center justify-center p-4"
          style={{ position: 'relative', zIndex: 10 }}
        >
          <div className="max-w-2xl w-full border border-[#ff0040] bg-[#0d0d0d] p-6">
            <div className="text-[#ff0040] text-center mb-6">
              <div className="text-4xl font-bold mb-2" style={{ textShadow: '0 0 10px #ff0040' }}>
                ARAGORA // CRITICAL ERROR
              </div>
              <div className="text-[#ffff00] text-sm">
                {isHydrationError
                  ? 'Rendering mismatch detected -- try refreshing'
                  : 'System encountered a fatal error'}
              </div>
            </div>

            <div className="bg-[#0a0a0a] border border-[#333] p-4 mb-4 text-[#888] text-sm overflow-x-auto">
              <div className="mb-2 text-[#ff0040] font-bold">
                {'>'} {error.message || 'Fatal system error'}
              </div>
              {error.digest && (
                <div className="text-[#666] text-xs mt-2">Error digest: {error.digest}</div>
              )}
            </div>

            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem' }}>
              <button
                onClick={reset}
                className="flex-1 border border-[#00ff88] text-[#00ff88] py-3 px-4 hover:bg-[#00ff88] hover:text-[#0a0a0a] transition-colors font-bold"
              >
                {'>'} RETRY
              </button>
              <button
                onClick={handleHardRefresh}
                className="flex-1 border border-[#39ff14] text-[#39ff14] py-3 px-4 hover:bg-[#39ff14] hover:text-[#0a0a0a] transition-colors font-bold"
                title="Force full page reload"
              >
                {'>'} HARD REFRESH
              </button>
            </div>

            {/* Diagnostics panel */}
            <button
              onClick={() => setShowDiagnostics(!showDiagnostics)}
              className="w-full text-left text-xs text-[#666] hover:text-[#39ff14] transition-colors mb-2"
            >
              {showDiagnostics ? '[-]' : '[+]'} DIAGNOSTICS
            </button>

            {showDiagnostics && (
              <div
                className="bg-[#0a0a0a] border border-[#333] p-3 text-xs"
                style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}
              >
                <div>
                  <span className="text-[#666]">Timestamp: </span>
                  <span className="text-[#00ffff]">{timestamp}</span>
                </div>
                <div>
                  <span className="text-[#666]">Error: </span>
                  <span className="text-[#e0e0e0]">{error.name || 'Unknown'}</span>
                </div>
                <div>
                  <span className="text-[#666]">Message: </span>
                  <span className="text-[#ff0040]">{error.message || 'N/A'}</span>
                </div>
                <div>
                  <span className="text-[#666]">URL: </span>
                  <span className="text-[#e0e0e0]">
                    {typeof window !== 'undefined' ? window.location.href : 'SSR'}
                  </span>
                </div>
                <div>
                  <span className="text-[#666]">Hydration Issue: </span>
                  <span style={{ color: isHydrationError ? '#ffff00' : '#39ff14' }}>
                    {isHydrationError ? 'YES' : 'NO'}
                  </span>
                </div>
                {error.stack && (
                  <div>
                    <button
                      onClick={() => setShowStack(!showStack)}
                      className="text-[#666] hover:text-[#39ff14] transition-colors mb-1"
                    >
                      {showStack ? '[-]' : '[+]'} Stack Trace
                    </button>
                    {showStack && (
                      <pre
                        className="overflow-x-auto overflow-y-auto whitespace-pre-wrap"
                        style={{
                          fontSize: '10px',
                          color: '#666',
                          maxHeight: '10rem',
                          borderTop: '1px solid #333',
                          paddingTop: '0.5rem',
                          marginTop: '0.25rem',
                        }}
                      >
                        {error.stack}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="text-[#666] text-xs text-center mt-4">
              If problem persists, please report this issue
            </div>
          </div>
        </div>
      </body>
    </html>
  );
}
