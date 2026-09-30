'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const BreakpointsPanel = dynamic(
  () => import('@/components/BreakpointsPanel').then((m) => ({ default: m.BreakpointsPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-96 bg-surface rounded" />
      </div>
    ),
  },
);

export default function BreakpointsPage() {
  const { config: backendConfig } = useBackend();

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
                href="/checkpoints"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [SAVES]
              </Link>
              <Link
                href="/impasse"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [IMPASSE]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">Breakpoints</h1>
            <p className="text-text-muted font-theme-data text-sm">
              Human-in-the-loop intervention points. Review and resolve pending breakpoints from
              running debates.
            </p>
          </div>

          <div className="grid gap-6">
            {/* Info Card */}
            <div className="card p-4 border-l-4 border-[var(--acid-cyan)]">
              <h3 className="font-theme-data text-[var(--acid-cyan)] mb-2">How Breakpoints Work</h3>
              <ul className="text-sm font-theme-data text-text-muted space-y-1">
                <li>&#x2022; Debates pause when Trickster detects hollow consensus</li>
                <li>&#x2022; Critical decisions require human approval before proceeding</li>
                <li>&#x2022; You can continue, pause, or abort the debate</li>
                <li>&#x2022; Resolution history is logged for audit trails</li>
              </ul>
            </div>

            {/* Breakpoints Panel */}
            <PanelErrorBoundary panelName="Breakpoints">
              <BreakpointsPanel apiBase={backendConfig.api} />
            </PanelErrorBoundary>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // BREAKPOINTS VIEW</p>
        </footer>
      </main>
    </>
  );
}
