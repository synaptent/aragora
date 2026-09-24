'use client';

import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const TrainingExportPanel = dynamic(
  () =>
    import('@/components/TrainingExportPanel').then((m) => ({ default: m.TrainingExportPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-96 bg-surface rounded" />
      </div>
    ),
  },
);

export default function TrainingPage() {
  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              Training Data Export
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Export debate outcomes as training data for ML fine-tuning. Supports SFT, DPO, and
              Gauntlet formats.
            </p>
          </div>

          <PanelErrorBoundary panelName="Training Export">
            <TrainingExportPanel />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // TRAINING DATA EXPORT</p>
        </footer>
      </main>
    </>
  );
}
