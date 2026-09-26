'use client';

import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const ReviewsPanel = dynamic(
  () => import('@/components/ReviewsPanel').then((m) => ({ default: m.ReviewsPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-96 bg-surface rounded" />
      </div>
    ),
  },
);

export default function ReviewsPage() {
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
              <span>📝</span> Code Reviews
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Shareable multi-agent code reviews. When AI models agree, you know it matters.
            </p>
          </div>

          <div className="grid gap-6">
            <PanelErrorBoundary panelName="Reviews">
              <ReviewsPanel apiBase={backendConfig.api} />
            </PanelErrorBoundary>

            {/* Usage hints */}
            <div className="bg-surface border border-border rounded-lg p-4">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">
                Create a Shareable Review
              </h3>
              <ul className="text-xs text-text-muted space-y-2 font-theme-data">
                <li className="flex items-start gap-2">
                  <span className="text-[var(--acid-cyan)]">&gt;</span>
                  <code className="bg-bg px-2 py-0.5">git diff main | aragora review --share</code>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-[var(--acid-cyan)]">&gt;</span>
                  <code className="bg-bg px-2 py-0.5">
                    aragora review https://github.com/org/repo/pull/123 --share
                  </code>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-[var(--acid-cyan)]">&gt;</span>
                  <code className="bg-bg px-2 py-0.5">aragora review --demo</code>
                  <span className="text-text-muted/70">(try without API keys)</span>
                </li>
              </ul>
              <div className="mt-4 pt-3 border-t border-border">
                <h4 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-2">
                  What you get:
                </h4>
                <ul className="text-xs text-text-muted space-y-1 font-theme-data">
                  <li>
                    • <span className="text-red-400">Unanimous Issues</span> - All AI models agree
                    (fix these first)
                  </li>
                  <li>
                    • <span className="text-amber-400">Split Opinions</span> - Models disagree (you
                    decide)
                  </li>
                  <li>
                    • <span className="text-[var(--accent)]">Agreement Score</span> - How much the
                    AI team aligned
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}
