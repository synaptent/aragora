'use client';

import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { LiveEloRankingsPanel } from '@/components/leaderboard/LiveEloRankingsPanel';

const EloTrendChart = dynamic(
  () =>
    import('@/components/leaderboard/EloTrendChart').then((m) => ({ default: m.EloTrendChart })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[280px] bg-surface rounded" />
      </div>
    ),
  },
);

const DomainLeaderboard = dynamic(
  () =>
    import('@/components/leaderboard/DomainLeaderboard').then((m) => ({
      default: m.DomainLeaderboard,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[300px] bg-surface rounded" />
      </div>
    ),
  },
);

export default function LeaderboardPage() {
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
              {'>'} AGENT LEADERBOARD
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Live ELO rankings with calibration scores and debate counts sourced from the canonical
              rankings API.
            </p>
          </div>

          {/* ELO Trend Chart — top 5 agents over time */}
          <div className="mb-6">
            <PanelErrorBoundary panelName="ELO Trends">
              <EloTrendChart maxPoints={30} height={240} />
            </PanelErrorBoundary>
          </div>

          {/* Domain Leaderboards — filterable by debate domain */}
          <div className="mb-6">
            <PanelErrorBoundary panelName="Domain Leaderboard">
              <DomainLeaderboard />
            </PanelErrorBoundary>
          </div>

          {/* Live ELO Rankings */}
          <PanelErrorBoundary panelName="Leaderboard">
            <LiveEloRankingsPanel apiBase={backendConfig.api} />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // AGENT LEADERBOARD</p>
        </footer>
      </main>
    </>
  );
}
