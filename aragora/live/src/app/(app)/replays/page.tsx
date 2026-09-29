'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const ReplayBrowser = dynamic(
  () => import('@/components/ReplayBrowser').then((m) => ({ default: m.ReplayBrowser })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-96 bg-surface rounded" />
      </div>
    ),
  },
);

export default function ReplaysPage() {
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
                href="/gallery"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [GALLERY]
              </Link>
              <Link
                href="/insights"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [INSIGHTS]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">Debate Replays</h1>
            <p className="text-text-muted font-theme-data text-sm">
              Browse and replay historical debates. Fork from any point to explore alternative
              paths.
            </p>
          </div>

          <div className="grid gap-6">
            <PanelErrorBoundary panelName="Replay Browser">
              <ReplayBrowser />
            </PanelErrorBoundary>

            {/* Usage hints */}
            <div className="bg-surface border border-border rounded-lg p-4">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">Quick Tips</h3>
              <ul className="text-xs text-text-muted space-y-2 font-theme-data">
                <li className="flex items-start gap-2">
                  <span className="text-[var(--acid-cyan)]">&gt;</span>
                  Click on any event to highlight similar arguments across the debate
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-[var(--acid-cyan)]">&gt;</span>
                  Use &quot;Fork Here&quot; to create a branch point for exploring alternative
                  debate paths
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-[var(--acid-cyan)]">&gt;</span>
                  Convergence patterns show where agents reached consensus or diverged
                </li>
              </ul>
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // REPLAY BROWSER</p>
        </footer>
      </main>
    </>
  );
}
