'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { logger } from '@/utils/logger';
import type { StreamEvent } from '@/types/events';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

interface TournamentSummary {
  tournament_id: string;
  participants: number;
  total_matches: number;
  top_agent: string | null;
}

interface Standing {
  agent: string;
  wins: number;
  losses: number;
  draws: number;
  points: number;
  total_score: number;
  win_rate: number;
}

interface TournamentPanelProps {
  apiBase?: string;
  events?: StreamEvent[];
}

const DEFAULT_API_BASE = API_BASE_URL;

export function TournamentPanel({ apiBase = DEFAULT_API_BASE, events = [] }: TournamentPanelProps) {
  const { tokens } = useAuth();
  const [tournaments, setTournaments] = useState<TournamentSummary[]>([]);
  const [selectedTournament, setSelectedTournament] = useState<string | null>(null);
  const [standings, setStandings] = useState<Standing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTournaments = useCallback(async () => {
    try {
      setLoading(true);
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const res = await fetch(`${apiBase}/api/tournaments`, { headers });
      if (res.ok) {
        const data = await res.json();
        setTournaments(data.tournaments || []);
        // Auto-select first tournament if available
        if (data.tournaments?.length > 0 && !selectedTournament) {
          setSelectedTournament(data.tournaments[0].tournament_id);
        }
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch tournaments');
    } finally {
      setLoading(false);
    }
  }, [apiBase, selectedTournament, tokens?.access_token]);

  const fetchStandings = useCallback(
    async (tournamentId: string) => {
      try {
        const headers: HeadersInit = { 'Content-Type': 'application/json' };
        if (tokens?.access_token) {
          headers['Authorization'] = `Bearer ${tokens.access_token}`;
        }
        const res = await fetch(`${apiBase}/api/tournaments/${tournamentId}/standings`, {
          headers,
        });
        if (res.ok) {
          const data = await res.json();
          setStandings(data.standings || []);
        }
      } catch (err) {
        logger.error('Failed to fetch standings:', err);
      }
    },
    [apiBase, tokens?.access_token],
  );

  // Use ref to store latest fetchTournaments to avoid interval recreation
  const fetchTournamentsRef = useRef(fetchTournaments);
  fetchTournamentsRef.current = fetchTournaments;

  useEffect(() => {
    fetchTournaments();
  }, [fetchTournaments]);

  // Separate effect for interval - runs once, uses ref (fallback for when events not available)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchTournamentsRef.current();
    }, 60000);
    return () => clearInterval(interval);
  }, []); // Empty deps - interval created once

  // Refresh on relevant events (match_recorded, leaderboard_update)
  const latestMatchEvent = useMemo(() => {
    const relevant = events.filter(
      (e) => e.type === 'match_recorded' || e.type === 'leaderboard_update',
    );
    return relevant[relevant.length - 1];
  }, [events]);

  useEffect(() => {
    if (latestMatchEvent) {
      fetchTournaments();
      if (selectedTournament) {
        fetchStandings(selectedTournament);
      }
    }
  }, [latestMatchEvent, fetchTournaments, fetchStandings, selectedTournament]);

  useEffect(() => {
    if (selectedTournament) {
      fetchStandings(selectedTournament);
    }
  }, [selectedTournament, fetchStandings]);

  const getRankBadge = (rank: number): string => {
    if (rank === 1) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
    if (rank === 2) return 'bg-zinc-400/20 text-zinc-300 border-zinc-400/30';
    if (rank === 3) return 'bg-amber-600/20 text-amber-500 border-amber-600/30';
    return 'bg-surface text-text-muted border-border';
  };

  const getWinRateColor = (rate: number): string => {
    if (rate >= 0.7) return 'text-green-400';
    if (rate >= 0.5) return 'text-yellow-400';
    return 'text-red-400';
  };

  return (
    <div className="panel">
      <div className="panel-header mb-4">
        <h3 className="panel-title flex items-center gap-2">
          <span className="text-accent">&#9733;</span>
          Tournaments
        </h3>
        <button
          onClick={fetchTournaments}
          className="px-2 py-1 bg-surface border border-border rounded text-sm text-text hover:bg-surface-hover"
        >
          Refresh
        </button>
      </div>

      {loading && tournaments.length === 0 && (
        <div className="text-center text-text-muted py-4">Loading tournaments...</div>
      )}

      {error && <div className="text-center text-red-400 py-4 text-sm">{error}</div>}

      {!loading && tournaments.length === 0 && !error && (
        <div className="text-center text-text-muted py-4 text-sm">
          No tournaments yet. Tournaments are created during structured agent competitions.
        </div>
      )}

      {tournaments.length > 0 && (
        <>
          {/* Tournament Selector */}
          <div className="mb-4">
            <select
              value={selectedTournament || ''}
              onChange={(e) => setSelectedTournament(e.target.value)}
              className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-text"
            >
              {tournaments.map((t) => (
                <option key={t.tournament_id} value={t.tournament_id}>
                  {t.tournament_id} ({t.participants} agents, {t.total_matches} matches)
                </option>
              ))}
            </select>
          </div>

          {/* Tournament Stats */}
          {selectedTournament && (
            <div className="grid grid-cols-3 gap-2 mb-4">
              {(() => {
                const t = tournaments.find((x) => x.tournament_id === selectedTournament);
                return (
                  <>
                    <div className="bg-bg rounded p-2 text-center">
                      <div className="text-lg font-bold text-accent">{t?.participants || 0}</div>
                      <div className="text-xs text-text-muted">Agents</div>
                    </div>
                    <div className="bg-bg rounded p-2 text-center">
                      <div className="text-lg font-bold text-text">{t?.total_matches || 0}</div>
                      <div className="text-xs text-text-muted">Matches</div>
                    </div>
                    <div className="bg-bg rounded p-2 text-center">
                      <div
                        className="text-lg font-bold text-yellow-400 truncate"
                        title={t?.top_agent || 'N/A'}
                      >
                        {t?.top_agent || 'N/A'}
                      </div>
                      <div className="text-xs text-text-muted">Leader</div>
                    </div>
                  </>
                );
              })()}
            </div>
          )}

          {/* Standings */}
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {standings.map((standing, index) => (
              <div
                key={standing.agent}
                className="flex items-center gap-3 p-2 bg-bg border border-border rounded-lg hover:border-accent/50 transition-colors"
              >
                {/* Rank Badge */}
                <div
                  className={`w-7 h-7 flex items-center justify-center rounded-full text-xs font-bold border ${getRankBadge(index + 1)}`}
                >
                  {index + 1}
                </div>

                {/* Agent Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-text truncate">{standing.agent}</span>
                    <span className="text-sm font-theme-data text-accent">
                      {standing.points.toFixed(1)} pts
                    </span>
                  </div>
                  <div className="text-xs text-text-muted">
                    {standing.wins}W-{standing.losses}L-{standing.draws}D
                  </div>
                </div>

                {/* Win Rate */}
                <div className={`text-sm font-theme-data ${getWinRateColor(standing.win_rate)}`}>
                  {(standing.win_rate * 100).toFixed(0)}%
                </div>
              </div>
            ))}

            {standings.length === 0 && selectedTournament && (
              <div className="text-center text-text-muted py-4 text-sm">
                No standings available for this tournament.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
