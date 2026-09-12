'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAragoraClient } from '@/hooks/useAragoraClient';
import { LoadingSpinner } from './LoadingSpinner';
import { ApiError } from './ApiError';
import type { Tournament, TournamentMatch, TournamentStanding } from '@/lib/aragora-client';

interface TournamentBracketProps {
  tournamentId?: string;
  onSelectTournament?: (id: string) => void;
}

export function TournamentBracket({ tournamentId, onSelectTournament }: TournamentBracketProps) {
  const client = useAragoraClient();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Data state
  const [tournaments, setTournaments] = useState<Tournament[]>([]);
  const [selectedTournament, setSelectedTournament] = useState<Tournament | null>(null);
  const [bracket, setBracket] = useState<TournamentMatch[]>([]);
  const [standings, setStandings] = useState<TournamentStanding[]>([]);

  const fetchTournaments = useCallback(async () => {
    if (!client) return;
    setLoading(true);
    setError(null);

    try {
      const res = await client.tournaments.list({ limit: 20 });
      setTournaments(res.tournaments || []);

      // If we have a specific tournamentId, fetch that one
      if (tournamentId) {
        const tourney = await client.tournaments.get(tournamentId);
        setSelectedTournament(tourney.tournament);
        const [bracketRes, standingsRes] = await Promise.all([
          client.tournaments.bracket(tournamentId).catch(() => ({ bracket: [] })),
          client.tournaments.standings(tournamentId).catch(() => ({ standings: [] })),
        ]);
        setBracket(bracketRes.bracket || []);
        setStandings(standingsRes.standings || []);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load tournaments');
    } finally {
      setLoading(false);
    }
  }, [client, tournamentId]);

  useEffect(() => {
    fetchTournaments();
  }, [fetchTournaments]);

  const selectTournament = async (id: string) => {
    if (!client) return;
    setLoading(true);
    try {
      const tourney = await client.tournaments.get(id);
      setSelectedTournament(tourney.tournament);
      const [bracketRes, standingsRes] = await Promise.all([
        client.tournaments.bracket(id).catch(() => ({ bracket: [] })),
        client.tournaments.standings(id).catch(() => ({ standings: [] })),
      ]);
      setBracket(bracketRes.bracket || []);
      setStandings(standingsRes.standings || []);
      onSelectTournament?.(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load tournament');
    } finally {
      setLoading(false);
    }
  };

  if (loading && !selectedTournament) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <LoadingSpinner />
      </div>
    );
  }

  if (error && !selectedTournament) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <ApiError error={error} onRetry={fetchTournaments} />
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-700">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <span className="text-yellow-400">&#x1F3C6;</span>
          Tournaments
        </h2>
        {selectedTournament && (
          <p className="text-sm text-slate-400 mt-1">
            {selectedTournament.name} • {selectedTournament.status}
          </p>
        )}
      </div>

      {/* Tournament List (if none selected) */}
      {!selectedTournament && (
        <div className="p-4 space-y-2 max-h-96 overflow-y-auto">
          {tournaments.length === 0 ? (
            <p className="text-slate-400 text-center py-4">No tournaments found</p>
          ) : (
            tournaments.map((t) => (
              <button
                key={t.id}
                onClick={() => selectTournament(t.id)}
                className="w-full text-left p-3 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-white font-medium">{t.name}</p>
                    <p className="text-sm text-slate-400">{t.topic}</p>
                  </div>
                  <div className="text-right">
                    <StatusBadge status={t.status} />
                    <p className="text-xs text-slate-400 mt-1">{t.participants.length} agents</p>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      )}

      {/* Tournament Detail View */}
      {selectedTournament && (
        <div className="p-4">
          {/* Back button */}
          <button
            onClick={() => setSelectedTournament(null)}
            className="text-sm text-blue-400 hover:text-blue-300 mb-4 flex items-center gap-1"
          >
            ← Back to tournaments
          </button>

          {/* Tournament Info */}
          <div className="mb-6">
            <h3 className="text-xl font-semibold text-white">{selectedTournament.name}</h3>
            <p className="text-slate-400">{selectedTournament.topic}</p>
            <div className="flex items-center gap-4 mt-2">
              <StatusBadge status={selectedTournament.status} />
              <span className="text-sm text-slate-400">
                {selectedTournament.bracket_type.replace('_', ' ')}
              </span>
              {selectedTournament.winner && (
                <span className="text-sm text-yellow-400">Winner: {selectedTournament.winner}</span>
              )}
            </div>
          </div>

          {/* Bracket View */}
          {bracket.length > 0 && (
            <div className="mb-6">
              <h4 className="text-sm font-medium text-slate-300 mb-3">Bracket</h4>
              <BracketView matches={bracket} />
            </div>
          )}

          {/* Standings */}
          {standings.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-slate-300 mb-3">Standings</h4>
              <div className="space-y-2">
                {standings.map((s, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between p-3 bg-slate-800 rounded-lg"
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={`w-6 h-6 rounded-full flex items-center justify-center text-sm font-bold ${
                          s.rank === 1
                            ? 'bg-yellow-500 text-black'
                            : s.rank === 2
                              ? 'bg-slate-300 text-black'
                              : s.rank === 3
                                ? 'bg-amber-600 text-white'
                                : 'bg-slate-700 text-slate-300'
                        }`}
                      >
                        {s.rank}
                      </span>
                      <span className="text-white">{s.agent_id}</span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-sm text-green-400">{s.wins}W</span>
                      <span className="text-sm text-red-400">{s.losses}L</span>
                      <span className="text-sm text-blue-400">{s.points}pts</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors = {
    pending: 'bg-slate-600 text-slate-200',
    in_progress: 'bg-blue-600 text-white',
    completed: 'bg-green-600 text-white',
  };
  const color = colors[status as keyof typeof colors] || colors.pending;
  return (
    <span className={`px-2 py-1 rounded text-xs font-medium ${color}`}>
      {status.replace('_', ' ')}
    </span>
  );
}

function BracketView({ matches }: { matches: TournamentMatch[] }) {
  // Group matches by round
  const rounds = matches.reduce<Record<number, TournamentMatch[]>>((acc, match) => {
    if (!acc[match.round]) acc[match.round] = [];
    acc[match.round].push(match);
    return acc;
  }, {});

  const roundNumbers = Object.keys(rounds)
    .map(Number)
    .sort((a, b) => a - b);

  return (
    <div className="flex gap-4 overflow-x-auto pb-4">
      {roundNumbers.map((roundNum) => (
        <div key={roundNum} className="flex-shrink-0 min-w-48">
          <p className="text-xs text-slate-400 mb-2">Round {roundNum}</p>
          <div className="space-y-2">
            {rounds[roundNum].map((match, i) => (
              <MatchCard key={i} match={match} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function MatchCard({ match }: { match: TournamentMatch }) {
  const isComplete = match.status === 'completed';
  const isP1Winner = match.winner === match.participant1;
  const isP2Winner = match.winner === match.participant2;

  return (
    <div className="bg-slate-800 rounded-lg p-2 border border-slate-700">
      <div
        className={`flex items-center justify-between p-2 rounded ${
          isP1Winner ? 'bg-green-900/30 border border-green-700' : ''
        }`}
      >
        <span className={`text-sm ${isP1Winner ? 'text-green-400 font-medium' : 'text-white'}`}>
          {match.participant1 || 'TBD'}
        </span>
        {isP1Winner && <span className="text-green-400">&#x2713;</span>}
      </div>
      <div className="text-center text-slate-500 text-xs my-1">vs</div>
      <div
        className={`flex items-center justify-between p-2 rounded ${
          isP2Winner ? 'bg-green-900/30 border border-green-700' : ''
        }`}
      >
        <span className={`text-sm ${isP2Winner ? 'text-green-400 font-medium' : 'text-white'}`}>
          {match.participant2 || 'TBD'}
        </span>
        {isP2Winner && <span className="text-green-400">&#x2713;</span>}
      </div>
      {!isComplete && (
        <div className="text-center mt-2">
          <StatusBadge status={match.status} />
        </div>
      )}
    </div>
  );
}

export default TournamentBracket;
