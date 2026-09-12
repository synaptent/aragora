'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const MemoryAnalyticsPanel = dynamic(
  () =>
    import('@/components/MemoryAnalyticsPanel').then((m) => ({ default: m.MemoryAnalyticsPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[500px] bg-surface rounded" />
      </div>
    ),
  },
);

export default function MemoryAnalyticsPage() {
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
                href="/memory"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [MEMORY]
              </Link>
              <Link
                href="/insights"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [INSIGHTS]
              </Link>
              <Link
                href="/analytics"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [ANALYTICS]
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
              {'>'} MEMORY ANALYTICS
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Monitor memory tier distribution, promotion statistics, learning velocity trends, and
              retrieval analytics.
            </p>
          </div>

          <div className="mb-6 grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-1">Fast Tier</h3>
              <p className="text-xs font-theme-data text-text-muted">
                1 min TTL - Immediate context
              </p>
            </div>
            <div className="p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded">
              <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-1">Medium Tier</h3>
              <p className="text-xs font-theme-data text-text-muted">1 hour TTL - Session memory</p>
            </div>
            <div className="p-4 border border-gold/30 bg-gold/5 rounded">
              <h3 className="text-sm font-theme-data text-gold mb-1">Slow Tier</h3>
              <p className="text-xs font-theme-data text-text-muted">1 day TTL - Cross-session</p>
            </div>
            <div className="p-4 border border-acid-purple/30 bg-acid-purple/5 rounded">
              <h3 className="text-sm font-theme-data text-acid-purple mb-1">Glacial Tier</h3>
              <p className="text-xs font-theme-data text-text-muted">
                1 week TTL - Long-term patterns
              </p>
            </div>
          </div>

          <div className="mb-6 p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded">
            <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-2">
              Analytics Metrics
            </h3>
            <ul className="text-xs font-theme-data text-text-muted space-y-1">
              <li>
                - <span className="text-[var(--accent)]">Tier Distribution</span>: Memory allocation
                across tiers
              </li>
              <li>
                - <span className="text-[var(--accent)]">Promotion Rate</span>: How often memories
                move to slower tiers
              </li>
              <li>
                - <span className="text-[var(--accent)]">Learning Velocity</span>: Rate of new
                knowledge acquisition
              </li>
              <li>
                - <span className="text-[var(--accent)]">Retrieval Efficiency</span>: Cache hit
                rates and latency
              </li>
            </ul>
          </div>

          <PanelErrorBoundary panelName="Memory Analytics">
            <MemoryAnalyticsPanel apiBase={backendConfig.api} />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // MEMORY ANALYTICS</p>
        </footer>
      </main>
    </>
  );
}
