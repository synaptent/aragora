'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const CapabilityProbePanel = dynamic(
  () =>
    import('@/components/CapabilityProbePanel').then((m) => ({ default: m.CapabilityProbePanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[500px] bg-surface rounded" />
      </div>
    ),
  },
);

export default function ProbePage() {
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
                href="/agents"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [AGENTS]
              </Link>
              <Link
                href="/leaderboard"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [LEADERBOARD]
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
              {'>'} CAPABILITY PROBES
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Test agent capabilities: contradiction detection, hallucination resistance, sycophancy
              testing, confidence calibration, and reasoning depth analysis.
            </p>
          </div>

          <div className="mb-6 p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded">
            <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-2">
              Available Probe Types
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs font-theme-data text-text-muted">
              <span>• Contradiction Detection</span>
              <span>• Hallucination Resistance</span>
              <span>• Sycophancy Testing</span>
              <span>• Confidence Calibration</span>
              <span>• Reasoning Depth</span>
              <span>• Knowledge Boundaries</span>
              <span>• Logical Consistency</span>
              <span>• Temporal Reasoning</span>
              <span>• Numerical Accuracy</span>
            </div>
          </div>

          <PanelErrorBoundary panelName="Capability Probes">
            <CapabilityProbePanel apiBase={backendConfig.api} />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // CAPABILITY PROBES</p>
        </footer>
      </main>
    </>
  );
}
