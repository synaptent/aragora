'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const CalibrationPanel = dynamic(
  () => import('@/components/CalibrationPanel').then((m) => ({ default: m.CalibrationPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[500px] bg-surface rounded" />
      </div>
    ),
  },
);

export default function CalibrationPage() {
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
                href="/agents"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [AGENTS]
              </Link>
              <Link
                href="/leaderboard"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [RANKS]
              </Link>
              <Link
                href="/probe"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [PROBE]
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
              {'>'} AGENT CALIBRATION
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Track agent confidence calibration, accuracy curves, and reliability metrics. Identify
              over-confident or under-confident agents.
            </p>
          </div>

          <div className="mb-6 p-4 border border-gold/30 bg-gold/5 rounded">
            <h3 className="text-sm font-theme-data text-gold mb-2">Calibration Metrics</h3>
            <ul className="text-xs font-theme-data text-text-muted space-y-1">
              <li>
                - <span className="text-[var(--accent)]">Expected Calibration Error (ECE)</span>:
                Lower is better
              </li>
              <li>
                - <span className="text-[var(--accent)]">Brier Score</span>: Prediction accuracy
                measure
              </li>
              <li>
                - <span className="text-[var(--accent)]">Reliability Diagrams</span>: Confidence vs
                accuracy curves
              </li>
              <li>
                - <span className="text-[var(--accent)]">Confidence Distribution</span>: How agents
                spread confidence
              </li>
            </ul>
          </div>

          <PanelErrorBoundary panelName="Calibration">
            <CalibrationPanel apiBase={backendConfig.api} events={[]} />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // AGENT CALIBRATION</p>
        </footer>
      </main>
    </>
  );
}
