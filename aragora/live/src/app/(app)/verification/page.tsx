'use client';

import Link from 'next/link';
import { ProofVisualizerPanel } from '@/components/ProofVisualizerPanel';
import { useBackend, BackendSelector } from '@/components/BackendSelector';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

export default function VerificationPage() {
  const { config } = useBackend();

  const backendConfig = { apiUrl: config.api, wsUrl: config.ws };

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
              <Link
                href="/debates"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [DEBATES]
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
              {'>'} FORMAL_VERIFICATION
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Verify claims using Z3 SMT solver or Lean4 theorem prover. Translate natural language
              to formal proofs.
            </p>
          </div>

          <PanelErrorBoundary panelName="Proof Visualizer">
            <ProofVisualizerPanel backendConfig={backendConfig} />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // FORMAL VERIFICATION</p>
        </footer>
      </main>
    </>
  );
}
