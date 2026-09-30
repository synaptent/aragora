'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { AgentLeaderboard, type AgentRankingEntry } from '@/components/analytics/AgentLeaderboard';
import { AgentRecommender } from '@/components/AgentRecommender';
import { TrustBadge } from '@/components/TrustBadge';
import { useSWRFetch } from '@/hooks/useSWRFetch';
import { AGENT_DISPLAY_NAMES } from '@/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentRankingsResponse {
  rankings?: AgentRankingEntry[];
  agents?: AgentRankingEntry[];
  leaderboard?: AgentRankingEntry[];
}

type EloTier = 'gold' | 'silver' | 'bronze' | 'iron';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getEloTier(elo: number): EloTier {
  if (elo >= 1600) return 'gold';
  if (elo >= 1400) return 'silver';
  if (elo >= 1200) return 'bronze';
  return 'iron';
}

const TIER_STYLES: Record<EloTier, { bg: string; text: string; label: string }> = {
  gold: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', label: 'GOLD' },
  silver: { bg: 'bg-gray-300/20', text: 'text-gray-300', label: 'SILVER' },
  bronze: { bg: 'bg-orange-500/20', text: 'text-orange-400', label: 'BRONZE' },
  iron: { bg: 'bg-gray-500/20', text: 'text-gray-500', label: 'IRON' },
};

function getDisplayName(agentName: string): string {
  return AGENT_DISPLAY_NAMES[agentName] || agentName;
}

// ---------------------------------------------------------------------------
// Tier Distribution Bar
// ---------------------------------------------------------------------------

function TierDistribution({ agents }: { agents: AgentRankingEntry[] }) {
  const distribution = useMemo(() => {
    const counts: Record<EloTier, number> = { gold: 0, silver: 0, bronze: 0, iron: 0 };
    agents.forEach((a) => {
      counts[getEloTier(a.elo)]++;
    });
    return counts;
  }, [agents]);

  const total = agents.length || 1;

  return (
    <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
      <h3 className="text-xs font-theme-data text-[var(--text-muted)] uppercase mb-3">
        ELO Tier Distribution
      </h3>
      <div className="flex h-4 rounded overflow-hidden mb-3">
        {(['gold', 'silver', 'bronze', 'iron'] as const).map((tier) => {
          const pct = (distribution[tier] / total) * 100;
          if (pct === 0) return null;
          return (
            <div
              key={tier}
              className={`${TIER_STYLES[tier].bg} border-r border-[var(--bg)] last:border-r-0`}
              style={{ width: `${pct}%` }}
              title={`${TIER_STYLES[tier].label}: ${distribution[tier]} agents`}
            />
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] font-theme-data">
        {(['gold', 'silver', 'bronze', 'iron'] as const).map((tier) => (
          <span key={tier} className={TIER_STYLES[tier].text}>
            {TIER_STYLES[tier].label} ({distribution[tier]})
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent Detail Cards
// ---------------------------------------------------------------------------

function AgentCards({ agents }: { agents: AgentRankingEntry[] }) {
  if (agents.length === 0) {
    return (
      <div className="text-center py-8 space-y-3">
        <p className="text-[var(--text-muted)] font-theme-data text-sm">No agent rankings yet</p>
        <p className="text-[var(--text-muted)]/60 font-theme-data text-xs max-w-sm mx-auto">
          Run debates to generate ELO ratings and see which agents perform best across topics.
        </p>
        <Link
          href="/debate"
          className="inline-block mt-2 px-4 py-1.5 text-xs font-theme-data border border-[var(--acid-green)]/40 text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors"
        >
          Start a debate
        </Link>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {agents.map((agent) => {
        const tier = getEloTier(agent.elo);
        const style = TIER_STYLES[tier];
        return (
          <div
            key={agent.agent_name}
            className="p-4 bg-[var(--surface)] border border-[var(--border)] hover:border-[var(--acid-green)]/50 transition-colors"
          >
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="font-theme-data text-sm text-[var(--acid-cyan)] flex items-center gap-1.5">
                  {getDisplayName(agent.agent_name)}
                  <TrustBadge calibration={agent.calibration ?? null} size="md" />
                </div>
                <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  {agent.agent_name}
                </div>
              </div>
              <span
                className={`px-2 py-0.5 text-[10px] font-theme-data border ${style.bg} ${style.text}`}
              >
                {style.label}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs font-theme-data">
              <div>
                <div className="text-[var(--text-muted)]">ELO</div>
                <div className="text-purple-400 font-bold">{Math.round(agent.elo)}</div>
              </div>
              <div>
                <div className="text-[var(--text-muted)]">Win Rate</div>
                <div className={agent.win_rate >= 50 ? 'text-[var(--acid-green)]' : 'text-red-400'}>
                  {agent.win_rate.toFixed(1)}%
                </div>
              </div>
              <div>
                <div className="text-[var(--text-muted)]">Debates</div>
                <div className="text-[var(--text)]">{agent.games_played}</div>
              </div>
              <div>
                <div className="text-[var(--text-muted)]">Calibration</div>
                <div className="text-[var(--acid-cyan)]">
                  {agent.calibration_score !== undefined
                    ? `${(agent.calibration_score * 100).toFixed(0)}%`
                    : '-'}
                </div>
              </div>
            </div>

            <div className="mt-3 pt-2 border-t border-[var(--border)] flex justify-between text-[10px] font-theme-data">
              <span>
                <span className="text-[var(--acid-green)]">{agent.wins}W</span>
                <span className="text-[var(--text-muted)]"> / </span>
                <span className="text-red-400">{agent.losses}L</span>
                <span className="text-[var(--text-muted)]"> / </span>
                <span className="text-yellow-400">{agent.draws}D</span>
              </span>
              {agent.response_time_ms !== undefined && (
                <span className="text-[var(--text-muted)]">{agent.response_time_ms}ms avg</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type ViewMode = 'leaderboard' | 'cards' | 'recommender';

export default function AgentsPage() {
  const [viewMode, setViewMode] = useState<ViewMode>('leaderboard');
  const [selectedAgent, setSelectedAgent] = useState<AgentRankingEntry | null>(null);

  // Fetch agent rankings from backend API
  const { data, error, isLoading } = useSWRFetch<AgentRankingsResponse>('/api/v1/agents/rankings', {
    refreshInterval: 60000,
  });

  const agents: AgentRankingEntry[] = useMemo(() => {
    if (!data) return [];
    const raw = data.rankings || data.agents || data.leaderboard || [];
    // Ensure rank is assigned if missing
    return raw.map((a, i) => ({ ...a, rank: a.rank || i + 1 }));
  }, [data]);

  const handleTeamSelect = (selectedAgents: string[]) => {
    const agentString = selectedAgents.join(',');
    navigator.clipboard.writeText(agentString);
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-2">
                  {'>'} AGENT LEADERBOARD
                </h1>
                <p className="text-xs text-[var(--text-muted)] font-theme-data">
                  Agent rankings by ELO rating, win rate, calibration scores, and debate
                  participation
                </p>
              </div>
              <div className="flex items-center gap-2">
                {(['leaderboard', 'cards', 'recommender'] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-3 py-1.5 text-xs font-theme-data border transition-colors ${
                      viewMode === mode
                        ? 'bg-[var(--acid-green)] text-[var(--bg)] border-[var(--acid-green)]'
                        : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--acid-green)] hover:border-[var(--acid-green)]/50'
                    }`}
                  >
                    {mode.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Error State */}
          {error && (
            <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
              Failed to load agent rankings. The backend may be unavailable.
            </div>
          )}

          {/* Summary Stats */}
          {agents.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                <div className="text-2xl font-theme-data text-[var(--acid-green)]">
                  {agents.length}
                </div>
                <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  Total Agents
                </div>
              </div>
              <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                <div className="text-2xl font-theme-data text-purple-400">
                  {Math.round(agents.reduce((sum, a) => sum + a.elo, 0) / agents.length)}
                </div>
                <div className="text-[10px] font-theme-data text-[var(--text-muted)]">Avg ELO</div>
              </div>
              <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                  {agents.reduce((sum, a) => sum + a.games_played, 0)}
                </div>
                <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  Total Debates
                </div>
              </div>
              <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                <div className="text-2xl font-theme-data text-yellow-400">
                  {agents.length > 0 ? Math.round(agents[0].elo) : '-'}
                </div>
                <div className="text-[10px] font-theme-data text-[var(--text-muted)]">Top ELO</div>
              </div>
            </div>
          )}

          {/* Tier Distribution */}
          {agents.length > 0 && <TierDistribution agents={agents} />}

          {/* View Content */}
          <div className="mt-6">
            {viewMode === 'leaderboard' && (
              <PanelErrorBoundary panelName="Agent Leaderboard">
                <AgentLeaderboard
                  agents={agents}
                  loading={isLoading}
                  title="AGENT RANKINGS"
                  limit={50}
                  onAgentClick={setSelectedAgent}
                />
              </PanelErrorBoundary>
            )}

            {viewMode === 'cards' && (
              <PanelErrorBoundary panelName="Agent Cards">
                {isLoading ? (
                  <div className="text-center py-8 text-[var(--text-muted)] font-theme-data animate-pulse">
                    Loading agents...
                  </div>
                ) : (
                  <AgentCards agents={agents} />
                )}
              </PanelErrorBoundary>
            )}

            {viewMode === 'recommender' && (
              <PanelErrorBoundary panelName="Agent Recommender">
                <div className="max-w-4xl">
                  <AgentRecommender onTeamSelect={handleTeamSelect} />
                </div>
              </PanelErrorBoundary>
            )}
          </div>

          {/* Selected Agent Detail */}
          {selectedAgent && viewMode === 'leaderboard' && (
            <div className="mt-6 p-4 bg-[var(--surface)] border border-[var(--acid-green)]/30">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="font-theme-data text-sm text-[var(--acid-green)] flex items-center gap-2">
                    {'>'} {getDisplayName(selectedAgent.agent_name)}
                    <TrustBadge calibration={selectedAgent.calibration ?? null} size="md" />
                  </h3>
                  <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    {selectedAgent.agent_name}
                  </span>
                </div>
                <button
                  onClick={() => setSelectedAgent(null)}
                  className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)]"
                >
                  [CLOSE]
                </button>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-theme-data">
                <div>
                  <div className="text-[var(--text-muted)]">Rank</div>
                  <div className="text-[var(--text)] font-bold">#{selectedAgent.rank}</div>
                </div>
                <div>
                  <div className="text-[var(--text-muted)]">ELO Rating</div>
                  <div className="text-purple-400 font-bold">{Math.round(selectedAgent.elo)}</div>
                </div>
                <div>
                  <div className="text-[var(--text-muted)]">Win Rate</div>
                  <div
                    className={
                      selectedAgent.win_rate >= 50 ? 'text-[var(--acid-green)]' : 'text-red-400'
                    }
                  >
                    {selectedAgent.win_rate.toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div className="text-[var(--text-muted)]">Debates</div>
                  <div className="text-[var(--text)]">{selectedAgent.games_played}</div>
                </div>
                <div>
                  <div className="text-[var(--text-muted)]">Wins</div>
                  <div className="text-[var(--acid-green)]">{selectedAgent.wins}</div>
                </div>
                <div>
                  <div className="text-[var(--text-muted)]">Losses</div>
                  <div className="text-red-400">{selectedAgent.losses}</div>
                </div>
                <div>
                  <div className="text-[var(--text-muted)]">Draws</div>
                  <div className="text-yellow-400">{selectedAgent.draws}</div>
                </div>
                <div>
                  <div className="text-[var(--text-muted)]">Calibration</div>
                  <div className="text-[var(--acid-cyan)]">
                    {selectedAgent.calibration_score !== undefined
                      ? `${(selectedAgent.calibration_score * 100).toFixed(1)}%`
                      : 'N/A'}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Quick Access */}
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/leaderboard"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Full Leaderboard
            </Link>
            <Link
              href="/calibration"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Calibration Details
            </Link>
            <Link
              href="/tournaments"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Tournaments
            </Link>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
            {'='.repeat(40)}
          </div>
          <p className="text-[var(--text-muted)]">{'>'} ARAGORA // AGENT LEADERBOARD</p>
        </footer>
      </main>
    </>
  );
}
