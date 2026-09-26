'use client';

import Link from 'next/link';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

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

interface AgentDetail {
  agent_id: string;
  name: string;
  provider: string;
  model: string;
  elo: number;
  elo_history: Array<{ date: string; elo: number }>;
  calibration: { brier_score: number | null; accuracy: number | null; total_predictions: number };
  performance: {
    total_debates: number;
    wins: number;
    losses: number;
    win_rate: number;
    avg_response_ms: number;
    error_rate: number;
    consensus_contributions: number;
  };
  domains: Array<{ name: string; elo: number; debates: number }>;
}

interface AgentDashboardResponse {
  agents: AgentDetail[];
  total: number;
}

export default function AgentPerformancePage() {
  const { config } = useBackend();

  const { data, isLoading } = useSWRFetch<{ data: AgentDashboardResponse }>(
    '/api/v1/system-intelligence/agent-performance',
    { refreshInterval: 30000, baseUrl: config.api },
  );

  const agents = data?.data?.agents || [];

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-3">
              <Link
                href="/leaderboard"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [LEADERBOARD]
              </Link>
              <Link
                href="/calibration"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [CALIBRATION]
              </Link>
              <Link
                href="/outcome-dashboard"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [OUTCOMES]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} AGENT PERFORMANCE DEEP DIVE
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Detailed per-agent ELO trajectories, calibration metrics (Brier score),
              domain-specific rankings, win rates, and response latency.
            </p>
          </div>

          {/* ELO Trend Chart */}
          <div className="mb-6">
            <PanelErrorBoundary panelName="ELO Trends">
              <EloTrendChart maxPoints={50} height={280} />
            </PanelErrorBoundary>
          </div>

          {/* Agent Cards */}
          <PanelErrorBoundary panelName="Agent Details">
            {isLoading ? (
              <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
                Loading agent data...
              </div>
            ) : agents.length === 0 ? (
              <div className="p-8 bg-surface border border-border rounded-lg text-center">
                <p className="text-text-muted font-theme-data">
                  No agent performance data available. Run some debates first.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {agents.map((agent) => (
                  <div
                    key={agent.agent_id}
                    className="p-4 bg-surface border border-border rounded-lg"
                  >
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <h3 className="font-theme-data text-lg text-text font-bold">
                          {agent.name}
                        </h3>
                        <span className="text-xs text-text-muted">
                          {agent.provider}/{agent.model}
                        </span>
                      </div>
                      <div className="text-right">
                        <div className="text-2xl font-theme-data font-bold text-[var(--accent)]">
                          {agent.elo}
                        </div>
                        <div className="text-xs text-text-muted">ELO Rating</div>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                      <div className="p-2 bg-bg rounded text-center">
                        <div className="text-lg font-theme-data font-bold text-text">
                          {agent.performance.total_debates}
                        </div>
                        <div className="text-xs text-text-muted">Debates</div>
                      </div>
                      <div className="p-2 bg-bg rounded text-center">
                        <div className="text-lg font-theme-data font-bold text-[var(--accent)]">
                          {(agent.performance.win_rate * 100).toFixed(0)}%
                        </div>
                        <div className="text-xs text-text-muted">Win Rate</div>
                      </div>
                      <div className="p-2 bg-bg rounded text-center">
                        <div className="text-lg font-theme-data font-bold text-blue-400">
                          {agent.calibration.brier_score !== null
                            ? agent.calibration.brier_score.toFixed(3)
                            : 'N/A'}
                        </div>
                        <div className="text-xs text-text-muted">Brier Score</div>
                      </div>
                      <div className="p-2 bg-bg rounded text-center">
                        <div className="text-lg font-theme-data font-bold text-purple-400">
                          {agent.calibration.accuracy !== null
                            ? `${(agent.calibration.accuracy * 100).toFixed(0)}%`
                            : 'N/A'}
                        </div>
                        <div className="text-xs text-text-muted">Cal. Accuracy</div>
                      </div>
                      <div className="p-2 bg-bg rounded text-center">
                        <div className="text-lg font-theme-data font-bold text-gold">
                          {agent.performance.avg_response_ms}ms
                        </div>
                        <div className="text-xs text-text-muted">Avg Latency</div>
                      </div>
                      <div className="p-2 bg-bg rounded text-center">
                        <div
                          className={`text-lg font-theme-data font-bold ${
                            agent.performance.error_rate > 0.1
                              ? 'text-red-400'
                              : 'text-[var(--accent)]'
                          }`}
                        >
                          {(agent.performance.error_rate * 100).toFixed(1)}%
                        </div>
                        <div className="text-xs text-text-muted">Error Rate</div>
                      </div>
                    </div>

                    {agent.domains && agent.domains.length > 0 && (
                      <div className="mt-3">
                        <h4 className="text-xs text-text-muted uppercase mb-1">
                          Domain-Specific ELO
                        </h4>
                        <div className="flex flex-wrap gap-2">
                          {agent.domains.map((domain) => (
                            <span
                              key={domain.name}
                              className="px-2 py-1 text-xs font-theme-data bg-bg rounded border border-border"
                            >
                              {domain.name}:{' '}
                              <span className="text-[var(--accent)]">{domain.elo}</span>
                              <span className="text-text-muted ml-1">({domain.debates})</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </PanelErrorBoundary>
        </div>

        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // AGENT PERFORMANCE</p>
        </footer>
      </main>
    </>
  );
}
