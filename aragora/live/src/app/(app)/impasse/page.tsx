'use client';

import { useState } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { DebateThisButton } from '@/components/DebateThisButton';

const ImpasseDetectionPanel = dynamic(
  () =>
    import('@/components/ImpasseDetectionPanel').then((m) => ({
      default: m.ImpasseDetectionPanel,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[500px] bg-surface rounded" />
      </div>
    ),
  },
);

export default function ImpassePage() {
  const { config: backendConfig } = useBackend();
  const [debateId, setDebateId] = useState<string>('');
  const [activeDebateId, setActiveDebateId] = useState<string | null>(null);

  const handleLoadDebate = () => {
    if (debateId.trim()) {
      setActiveDebateId(debateId.trim());
    }
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-3">
              <Link
                href="/"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [DASHBOARD]
              </Link>
              <Link
                href="/debates"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [DEBATES]
              </Link>
              <Link
                href="/insights"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [INSIGHTS]
              </Link>
              <Link
                href="/checkpoints"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [SAVES]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} IMPASSE DETECTION
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Detect debate deadlocks, identify pivot claims, and suggest fork points for branching
              discussions into alternative paths.
            </p>
          </div>

          <div className="mb-6 p-4 border border-warning/30 bg-warning/5 rounded">
            <h3 className="text-sm font-theme-data text-warning mb-2">Impasse Analysis Features</h3>
            <ul className="text-xs font-theme-data text-text-muted space-y-1">
              <li>
                - <span className="text-[var(--accent)]">Deadlock detection</span>: Identify when
                debates stall
              </li>
              <li>
                - <span className="text-[var(--accent)]">Pivot claims</span>: Find claims that could
                break the impasse
              </li>
              <li>
                - <span className="text-[var(--accent)]">Fork suggestions</span>: Branch debates
                into alternative paths
              </li>
              <li>
                - <span className="text-[var(--accent)]">Resolution strategies</span>: Recommended
                actions to progress
              </li>
            </ul>
          </div>

          {/* Debate ID Input */}
          <div className="mb-6 p-4 border border-[var(--accent)]/30 rounded">
            <label className="block text-sm font-theme-data text-text-muted mb-2">
              Enter Debate ID to Analyze
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={debateId}
                onChange={(e) => setDebateId(e.target.value)}
                placeholder="debate-uuid-here"
                className="flex-1 bg-bg border border-[var(--accent)]/30 px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
              />
              <button
                onClick={handleLoadDebate}
                className="px-4 py-2 bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] text-sm font-theme-data hover:bg-[var(--accent)]/20 transition-colors"
              >
                [ANALYZE]
              </button>
              <DebateThisButton
                question="How should we resolve this debate impasse?"
                source="impasse"
                context={
                  activeDebateId
                    ? `Impasse analysis for debate ${activeDebateId}`
                    : 'Debate deadlock detection and resolution'
                }
                variant="button"
              />
            </div>
          </div>

          {activeDebateId ? (
            <PanelErrorBoundary panelName="Impasse Detection">
              <ImpasseDetectionPanel debateId={activeDebateId} apiBase={backendConfig.api} />
            </PanelErrorBoundary>
          ) : (
            <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
              <p className="text-text-muted font-theme-data text-sm">
                Enter a debate ID above to analyze for impasses and fork opportunities.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // IMPASSE DETECTION</p>
        </footer>
      </main>
    </>
  );
}
