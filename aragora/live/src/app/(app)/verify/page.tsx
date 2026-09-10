'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const ProofVisualizerPanel = dynamic(
  () =>
    import('@/components/ProofVisualizerPanel').then((m) => ({ default: m.ProofVisualizerPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[600px] bg-surface rounded" />
      </div>
    ),
  },
);

export default function VerifyPage() {
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
                href="/verification"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [FORMAL]
              </Link>
              <Link
                href="/evidence"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [EVIDENCE]
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
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} PROOF VISUALIZER
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Interactive visualization of consensus proofs and verification trees. Explore the
              logical structure of debate outcomes.
            </p>
          </div>

          <div className="mb-6 p-4 border border-acid-purple/30 bg-acid-purple/5 rounded">
            <h3 className="text-sm font-theme-data text-acid-purple mb-2">Verification Features</h3>
            <ul className="text-xs font-theme-data text-text-muted space-y-1">
              <li>
                - <span className="text-[var(--accent)]">Proof trees</span>: Visual representation
                of logical arguments
              </li>
              <li>
                - <span className="text-[var(--accent)]">Dependency graphs</span>: Trace claim
                dependencies
              </li>
              <li>
                - <span className="text-[var(--accent)]">Z3/Lean integration</span>: Formal
                verification backends
              </li>
              <li>
                - <span className="text-[var(--accent)]">Export proofs</span>: Download in multiple
                formats
              </li>
            </ul>
          </div>

          <PanelErrorBoundary panelName="Proof Visualizer">
            <ProofVisualizerPanel
              backendConfig={{ apiUrl: backendConfig.api, wsUrl: backendConfig.ws }}
            />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // PROOF VISUALIZER</p>
        </footer>
      </main>
    </>
  );
}
