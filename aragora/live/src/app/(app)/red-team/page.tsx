'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const RedTeamAnalysisPanel = dynamic(
  () =>
    import('@/components/RedTeamAnalysisPanel').then((m) => ({ default: m.RedTeamAnalysisPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[600px] bg-surface rounded" />
      </div>
    ),
  },
);

export default function RedTeamPage() {
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
                href="/gauntlet"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [GAUNTLET]
              </Link>
              <Link
                href="/probe"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [PROBE]
              </Link>
              <Link
                href="/modes"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [MODES]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-warning mb-2">{'>'} RED TEAM ANALYSIS</h1>
            <p className="text-text-muted font-theme-data text-sm">
              Security and robustness testing with adversarial attacks. Stress-test arguments and
              find weaknesses in reasoning.
            </p>
          </div>

          <div className="mb-6 grid grid-cols-2 md:grid-cols-3 gap-4">
            <div className="p-4 border border-warning/30 bg-warning/5 rounded">
              <h3 className="text-sm font-theme-data text-warning mb-1">Logical Fallacy</h3>
              <p className="text-xs font-theme-data text-text-muted">
                Detect reasoning errors and logical inconsistencies
              </p>
            </div>
            <div className="p-4 border border-warning/30 bg-warning/5 rounded">
              <h3 className="text-sm font-theme-data text-warning mb-1">Edge Cases</h3>
              <p className="text-xs font-theme-data text-text-muted">
                Test boundary conditions and unusual scenarios
              </p>
            </div>
            <div className="p-4 border border-warning/30 bg-warning/5 rounded">
              <h3 className="text-sm font-theme-data text-warning mb-1">Assumptions</h3>
              <p className="text-xs font-theme-data text-text-muted">
                Challenge unstated premises and hidden biases
              </p>
            </div>
            <div className="p-4 border border-warning/30 bg-warning/5 rounded">
              <h3 className="text-sm font-theme-data text-warning mb-1">Counterexamples</h3>
              <p className="text-xs font-theme-data text-text-muted">
                Find cases that contradict conclusions
              </p>
            </div>
            <div className="p-4 border border-warning/30 bg-warning/5 rounded">
              <h3 className="text-sm font-theme-data text-warning mb-1">Scalability</h3>
              <p className="text-xs font-theme-data text-text-muted">
                Test how arguments hold under scale changes
              </p>
            </div>
            <div className="p-4 border border-warning/30 bg-warning/5 rounded">
              <h3 className="text-sm font-theme-data text-warning mb-1">Security</h3>
              <p className="text-xs font-theme-data text-text-muted">
                Identify potential exploit vectors
              </p>
            </div>
          </div>

          <PanelErrorBoundary panelName="Red Team Analysis">
            <RedTeamAnalysisPanel apiBase={backendConfig.api} />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // RED TEAM ANALYSIS</p>
        </footer>
      </main>
    </>
  );
}
