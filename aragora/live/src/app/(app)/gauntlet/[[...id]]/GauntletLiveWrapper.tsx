'use client';

import { useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { useParams, useRouter } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import Link from 'next/link';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { GauntletLive } from '@/components/gauntlet/GauntletLive';
import type { GauntletVerdict } from '@/hooks/useGauntletWebSocket';

// Dynamically import GauntletPanel for list view
const GauntletPanel = dynamic(
  () => import('@/components/GauntletPanel').then((m) => ({ default: m.GauntletPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-96 bg-surface rounded" />
      </div>
    ),
  },
);

// List view component (no ID)
function GauntletListView() {
  const { config: backendConfig } = useBackend();

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2 flex items-center gap-3">
              <span>&#x2694;</span> Gauntlet
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Adversarial stress-testing results. Find vulnerabilities before they find you.
            </p>
          </div>

          <div className="grid gap-6">
            <PanelErrorBoundary panelName="Gauntlet Results">
              <GauntletPanel apiBase={backendConfig.api} />
            </PanelErrorBoundary>

            {/* Usage hints */}
            <div className="bg-surface border border-border rounded-lg p-4">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">Quick Start</h3>
              <ul className="text-xs text-text-muted space-y-2 font-theme-data">
                <li className="flex items-start gap-2">
                  <span className="text-[var(--acid-cyan)]">&gt;</span>
                  <code className="bg-bg px-2 py-0.5">
                    aragora gauntlet spec.md --profile quick
                  </code>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-[var(--acid-cyan)]">&gt;</span>
                  <code className="bg-bg px-2 py-0.5">
                    aragora gauntlet policy.yaml --persona gdpr
                  </code>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-[var(--acid-cyan)]">&gt;</span>
                  <code className="bg-bg px-2 py-0.5">
                    aragora gauntlet arch.md --profile thorough --output report.html
                  </code>
                </li>
              </ul>
              <div className="mt-4 pt-3 border-t border-border">
                <p className="text-xs text-text-muted">
                  See{' '}
                  <a href="/about" className="text-[var(--acid-cyan)] hover:text-[var(--accent)]">
                    the documentation
                  </a>{' '}
                  for full documentation.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // GAUNTLET STRESS TESTING</p>
        </footer>
      </main>
    </>
  );
}

// Individual gauntlet view (with ID)
function GauntletDetailView({ gauntletId }: { gauntletId: string }) {
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const [copied, setCopied] = useState(false);
  const [verdict, setVerdict] = useState<GauntletVerdict | null>(null);

  const wsUrl = backendConfig.ws;

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, []);

  const handleComplete = useCallback((v: GauntletVerdict) => {
    setVerdict(v);
  }, []);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2 flex items-center gap-3">
                <span className="animate-pulse">&#x2694;</span> Live Gauntlet
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Real-time adversarial stress-testing in progress.
              </p>
            </div>
            <button
              onClick={handleCopy}
              className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
            >
              {copied ? '[COPIED!]' : '[SHARE LINK]'}
            </button>
          </div>

          <PanelErrorBoundary panelName="Gauntlet Live View">
            <GauntletLive gauntletId={gauntletId} wsUrl={wsUrl} onComplete={handleComplete} />
          </PanelErrorBoundary>

          {/* Post-completion actions */}
          {verdict && (
            <div className="mt-6 bg-surface border border-[var(--accent)]/30 p-4 rounded">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">Next Steps</h3>
              <div className="flex flex-wrap gap-3">
                <Link
                  href={`/api/gauntlet/${gauntletId}/receipt?format=html`}
                  target="_blank"
                  className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40 hover:bg-[var(--accent)]/30 transition-colors rounded"
                >
                  [DOWNLOAD RECEIPT]
                </Link>
                <Link
                  href="/gauntlet"
                  className="px-4 py-2 text-xs font-theme-data bg-surface text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/40 hover:bg-[var(--acid-cyan)]/10 transition-colors rounded"
                >
                  [VIEW ALL RESULTS]
                </Link>
                <button
                  onClick={() => router.push('/gauntlet')}
                  className="px-4 py-2 text-xs font-theme-data bg-surface text-text-muted border border-border hover:border-[var(--acid-cyan)]/40 transition-colors rounded"
                >
                  [RUN NEW GAUNTLET]
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // LIVE GAUNTLET STRESS TEST</p>
        </footer>
      </main>
    </>
  );
}

export function GauntletLiveWrapper() {
  const params = useParams();

  // Handle optional catch-all - id is an array or undefined
  const idArray = params.id as string[] | undefined;
  const gauntletId = idArray?.[0];

  // Show list view if no ID, detail view if ID provided
  if (!gauntletId) {
    return <GauntletListView />;
  }

  return <GauntletDetailView gauntletId={gauntletId} />;
}
