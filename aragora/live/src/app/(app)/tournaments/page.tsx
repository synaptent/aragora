'use client';

import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const TournamentViewerPanel = dynamic(
  () =>
    import('@/components/TournamentViewerPanel').then((m) => ({
      default: m.TournamentViewerPanel,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-96 bg-surface rounded" />
      </div>
    ),
  },
);

export default function TournamentsPage() {
  const { config: backendConfig } = useBackend();

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              Tournaments & Rankings
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Agent leaderboards, tournament brackets, and match history.
            </p>
          </div>

          <PanelErrorBoundary panelName="Tournament Viewer">
            <TournamentViewerPanel
              backendConfig={{ apiUrl: backendConfig.api, wsUrl: backendConfig.ws }}
            />
          </PanelErrorBoundary>
        </div>
      </main>
    </>
  );
}
