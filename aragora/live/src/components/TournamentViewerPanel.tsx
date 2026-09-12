'use client';

import { useState, useEffect, useCallback } from 'react';
import { ErrorWithRetry } from './RetryButton';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

interface Tournament {
  tournament_id: string;
  participants: number;
  total_matches: number;
  top_agent: string | null;
}

interface TournamentStanding {
  agent: string;
  wins: number;
  losses: number;
  draws: number;
  points: number;
  total_score: number;
  win_rate: number;
}

interface AgentRanking {
  name: string;
  elo: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number;
  consistency?: number;
  consistency_class?: string;
}

interface RecentMatch {
  debate_id: string;
  winner: string | null;
  participants: string[];
  domain?: string;
  created_at: string;
}

interface RankingStats {
  mean_elo: number;
  median_elo: number;
  total_agents: number;
  total_matches: number;
  trending_up: string[];
  trending_down: string[];
}

interface BackendConfig {
  apiUrl: string;
  wsUrl: string;
}

interface TournamentViewerPanelProps {
  backendConfig?: BackendConfig;
}

const DEFAULT_API_BASE = API_BASE_URL;

const ELO_TIERS: Record<string, { color: string; bg: string; label: string }> = {
  grandmaster: { color: 'text-acid-red', bg: 'bg-acid-red/20', label: 'Grandmaster' },
  master: { color: 'text-[var(--acid-yellow)]', bg: 'bg-acid-yellow/20', label: 'Master' },
  expert: { color: 'text-[var(--acid-cyan)]', bg: 'bg-[var(--acid-cyan)]/20', label: 'Expert' },
  intermediate: {
    color: 'text-[var(--accent)]',
    bg: 'bg-[var(--accent)]/20',
    label: 'Intermediate',
  },
  novice: { color: 'text-text-muted', bg: 'bg-surface', label: 'Novice' },
};

function getEloTier(elo: number): keyof typeof ELO_TIERS {
  if (elo >= 1800) return 'grandmaster';
  if (elo >= 1600) return 'master';
  if (elo >= 1400) return 'expert';
  if (elo >= 1200) return 'intermediate';
  return 'novice';
}

export function TournamentViewerPanel({ backendConfig }: TournamentViewerPanelProps) {
  const apiBase = backendConfig?.apiUrl || DEFAULT_API_BASE;

  const [tournaments, setTournaments] = useState<Tournament[]>([]);
  const [selectedTournament, setSelectedTournament] = useState<string | null>(null);
  const [standings, setStandings] = useState<TournamentStanding[]>([]);
  const [rankings, setRankings] = useState<AgentRanking[]>([]);
  const [matches, setMatches] = useState<RecentMatch[]>([]);
  const [stats, setStats] = useState<RankingStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'leaderboard' | 'tournaments' | 'matches'>(
    'leaderboard',
  );

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);

      const [tournamentsRes, leaderboardRes] = await Promise.allSettled([
        fetchWithRetry(`${apiBase}/api/tournaments`, undefined, { maxRetries: 2 }),
        fetchWithRetry(`${apiBase}/api/leaderboard-view?limit=20`, undefined, { maxRetries: 2 }),
      ]);

      // Handle tournaments
      if (tournamentsRes.status === 'fulfilled' && tournamentsRes.value.ok) {
        const data = await tournamentsRes.value.json();
        setTournaments(data.tournaments || []);
      } else {
        setTournaments([]);
      }

      // Handle leaderboard data
      if (leaderboardRes.status === 'fulfilled' && leaderboardRes.value.ok) {
        const data = await leaderboardRes.value.json();
        const lbData = data.data || data;

        if (lbData.rankings?.agents) {
          setRankings(lbData.rankings.agents);
        }
        if (lbData.matches?.matches) {
          setMatches(lbData.matches.matches);
        }
        if (lbData.stats) {
          setStats(lbData.stats);
        }
      } else {
        // Mock data for demo
        setRankings([]);
        setMatches([]);
        setStats({
          mean_elo: 1500,
          median_elo: 1500,
          total_agents: 0,
          total_matches: 0,
          trending_up: [],
          trending_down: [],
        });
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch tournament data');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  const fetchTournamentStandings = useCallback(
    async (tournamentId: string) => {
      try {
        const response = await fetchWithRetry(
          `${apiBase}/api/tournaments/${tournamentId}/standings`,
          undefined,
          { maxRetries: 2 },
        );

        if (response.ok) {
          const data = await response.json();
          setStandings(data.standings || []);
          setSelectedTournament(tournamentId);
        }
      } catch (err) {
        logger.error('Failed to fetch standings:', err);
      }
    },
    [apiBase],
  );

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading && rankings.length === 0) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3">
          <div className="animate-spin w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
          <span className="font-theme-data text-text-muted">Loading tournament data...</span>
        </div>
      </div>
    );
  }

  if (error && rankings.length === 0) {
    return <ErrorWithRetry error={error || 'Failed to load tournament data'} onRetry={fetchData} />;
  }

  return (
    <div className="space-y-6">
      {/* Stats Overview */}
      {stats && (
        <div className="card p-4">
          <h3 className="font-theme-data text-[var(--accent)] mb-4">System Overview</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="text-center">
              <div className="text-3xl font-theme-data text-[var(--accent)]">
                {stats.total_agents}
              </div>
              <div className="text-xs font-theme-data text-text-muted">Total Agents</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-theme-data text-[var(--acid-cyan)]">
                {stats.total_matches}
              </div>
              <div className="text-xs font-theme-data text-text-muted">Total Matches</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-theme-data text-[var(--acid-yellow)]">
                {Math.round(stats.mean_elo)}
              </div>
              <div className="text-xs font-theme-data text-text-muted">Mean ELO</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-theme-data text-acid-red">{tournaments.length}</div>
              <div className="text-xs font-theme-data text-text-muted">Tournaments</div>
            </div>
          </div>

          {/* Trending */}
          {(stats.trending_up.length > 0 || stats.trending_down.length > 0) && (
            <div className="mt-4 pt-4 border-t border-[var(--accent)]/20 flex gap-6 flex-wrap">
              {stats.trending_up.length > 0 && (
                <div>
                  <span className="text-xs font-theme-data text-text-muted">Trending Up: </span>
                  {stats.trending_up.slice(0, 3).map((agent, i) => (
                    <span key={agent} className="text-xs font-theme-data text-[var(--accent)]">
                      {agent}
                      {i < Math.min(stats.trending_up.length, 3) - 1 ? ', ' : ''}
                    </span>
                  ))}
                </div>
              )}
              {stats.trending_down.length > 0 && (
                <div>
                  <span className="text-xs font-theme-data text-text-muted">Trending Down: </span>
                  {stats.trending_down.slice(0, 3).map((agent, i) => (
                    <span key={agent} className="text-xs font-theme-data text-acid-red">
                      {agent}
                      {i < Math.min(stats.trending_down.length, 3) - 1 ? ', ' : ''}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-[var(--accent)]/20 pb-2">
        {(['leaderboard', 'tournaments', 'matches'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-theme-data text-sm transition-colors ${
              activeTab === tab
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Leaderboard Tab */}
      {activeTab === 'leaderboard' && (
        <div className="card p-4">
          <h3 className="font-theme-data text-[var(--accent)] mb-4">Agent Leaderboard</h3>
          {rankings.length === 0 ? (
            <p className="text-text-muted font-theme-data text-sm">
              No agents ranked yet. Run some debates to populate the leaderboard.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full font-theme-data text-sm">
                <thead>
                  <tr className="text-text-muted border-b border-[var(--accent)]/20">
                    <th className="text-left py-2 px-2">#</th>
                    <th className="text-left py-2 px-2">Agent</th>
                    <th className="text-right py-2 px-2">ELO</th>
                    <th className="text-right py-2 px-2">W</th>
                    <th className="text-right py-2 px-2">L</th>
                    <th className="text-right py-2 px-2">D</th>
                    <th className="text-right py-2 px-2">Win%</th>
                  </tr>
                </thead>
                <tbody>
                  {rankings.map((agent, idx) => {
                    const tier = getEloTier(agent.elo);
                    const tierInfo = ELO_TIERS[tier];
                    return (
                      <tr
                        key={agent.name}
                        className="border-b border-surface hover:bg-surface/50 transition-colors"
                      >
                        <td className="py-2 px-2 text-text-muted">{idx + 1}</td>
                        <td className="py-2 px-2">
                          <div className="flex items-center gap-2">
                            <span className={tierInfo.color}>{agent.name}</span>
                            <span
                              className={`text-xs px-1.5 py-0.5 rounded ${tierInfo.bg} ${tierInfo.color}`}
                            >
                              {tierInfo.label}
                            </span>
                          </div>
                        </td>
                        <td className="py-2 px-2 text-right">
                          <span className={tierInfo.color}>{Math.round(agent.elo)}</span>
                        </td>
                        <td className="py-2 px-2 text-right text-[var(--accent)]">{agent.wins}</td>
                        <td className="py-2 px-2 text-right text-acid-red">{agent.losses}</td>
                        <td className="py-2 px-2 text-right text-[var(--acid-yellow)]">
                          {agent.draws}
                        </td>
                        <td className="py-2 px-2 text-right">
                          {((agent.win_rate || 0) * 100).toFixed(1)}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tournaments Tab */}
      {activeTab === 'tournaments' && (
        <div className="space-y-4">
          {/* Tournament List */}
          <div className="card p-4">
            <h3 className="font-theme-data text-[var(--accent)] mb-4">Available Tournaments</h3>
            {tournaments.length === 0 ? (
              <p className="text-text-muted font-theme-data text-sm">
                No tournaments found. Tournaments are created when running competitive evaluations.
              </p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {tournaments.map((tournament) => (
                  <button
                    key={tournament.tournament_id}
                    onClick={() => fetchTournamentStandings(tournament.tournament_id)}
                    className={`p-4 rounded border text-left transition-colors ${
                      selectedTournament === tournament.tournament_id
                        ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                        : 'border-[var(--accent)]/30 hover:border-[var(--accent)]/60 bg-surface'
                    }`}
                  >
                    <div className="font-theme-data text-[var(--acid-cyan)] text-sm mb-2">
                      {tournament.tournament_id}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs font-theme-data">
                      <div>
                        <span className="text-text-muted">Participants:</span>
                        <span className="text-text ml-1">{tournament.participants}</span>
                      </div>
                      <div>
                        <span className="text-text-muted">Matches:</span>
                        <span className="text-text ml-1">{tournament.total_matches}</span>
                      </div>
                    </div>
                    {tournament.top_agent && (
                      <div className="mt-2 text-xs font-theme-data">
                        <span className="text-text-muted">Leader:</span>
                        <span className="text-[var(--accent)] ml-1">{tournament.top_agent}</span>
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Selected Tournament Standings */}
          {selectedTournament && standings.length > 0 && (
            <div className="card p-4">
              <h3 className="font-theme-data text-[var(--accent)] mb-4">
                Standings: {selectedTournament}
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full font-theme-data text-sm">
                  <thead>
                    <tr className="text-text-muted border-b border-[var(--accent)]/20">
                      <th className="text-left py-2 px-2">#</th>
                      <th className="text-left py-2 px-2">Agent</th>
                      <th className="text-right py-2 px-2">Pts</th>
                      <th className="text-right py-2 px-2">W</th>
                      <th className="text-right py-2 px-2">L</th>
                      <th className="text-right py-2 px-2">D</th>
                      <th className="text-right py-2 px-2">Win%</th>
                      <th className="text-right py-2 px-2">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {standings.map((standing, idx) => (
                      <tr
                        key={standing.agent}
                        className={`border-b border-surface ${
                          idx === 0 ? 'bg-[var(--accent)]/5' : ''
                        }`}
                      >
                        <td className="py-2 px-2 text-text-muted">{idx === 0 ? '🏆' : idx + 1}</td>
                        <td className="py-2 px-2">
                          <span className={idx === 0 ? 'text-[var(--accent)]' : 'text-text'}>
                            {standing.agent}
                          </span>
                        </td>
                        <td className="py-2 px-2 text-right text-[var(--acid-cyan)]">
                          {standing.points}
                        </td>
                        <td className="py-2 px-2 text-right text-[var(--accent)]">
                          {standing.wins}
                        </td>
                        <td className="py-2 px-2 text-right text-acid-red">{standing.losses}</td>
                        <td className="py-2 px-2 text-right text-[var(--acid-yellow)]">
                          {standing.draws}
                        </td>
                        <td className="py-2 px-2 text-right">
                          {((standing.win_rate || 0) * 100).toFixed(1)}%
                        </td>
                        <td className="py-2 px-2 text-right text-text-muted">
                          {standing.total_score?.toFixed(1) || '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Matches Tab */}
      {activeTab === 'matches' && (
        <div className="card p-4">
          <h3 className="font-theme-data text-[var(--accent)] mb-4">Recent Matches</h3>
          {matches.length === 0 ? (
            <p className="text-text-muted font-theme-data text-sm">
              No matches recorded yet. Run debates to see match history here.
            </p>
          ) : (
            <div className="space-y-3">
              {matches.map((match, idx) => (
                <div
                  key={match.debate_id || idx}
                  className="p-3 bg-surface rounded border border-[var(--accent)]/20"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                      {match.debate_id?.slice(0, 8) || `match-${idx}`}
                    </span>
                    {match.created_at && (
                      <span className="font-theme-data text-xs text-text-muted">
                        {new Date(match.created_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2 font-theme-data text-sm">
                    {match.participants?.map((agent, i) => (
                      <span key={agent}>
                        <span
                          className={
                            match.winner === agent
                              ? 'text-[var(--accent)] font-bold'
                              : match.winner === null
                                ? 'text-[var(--acid-yellow)]'
                                : 'text-text-muted'
                          }
                        >
                          {agent}
                          {match.winner === agent && ' 👑'}
                        </span>
                        {i < match.participants.length - 1 && (
                          <span className="text-text-muted mx-2">vs</span>
                        )}
                      </span>
                    ))}
                  </div>

                  {match.domain && (
                    <div className="mt-2 text-xs font-theme-data text-text-muted">
                      Domain: {match.domain}
                    </div>
                  )}

                  {match.winner === null && (
                    <div className="mt-1 text-xs font-theme-data text-[var(--acid-yellow)]">
                      Draw
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-4">
        <button
          onClick={fetchData}
          disabled={loading}
          className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
        >
          {loading ? 'Refreshing...' : 'Refresh Data'}
        </button>
      </div>
    </div>
  );
}
