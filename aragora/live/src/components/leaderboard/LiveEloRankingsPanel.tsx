'use client';

import Link from 'next/link';
import { memo, useEffect, useMemo, useState } from 'react';
import { useAuth } from '@/context/AuthContext';
import { getConsistencyColor, getEloColor, getRankBadge } from './types';

interface LiveEloRankingsPanelProps {
  apiBase: string;
  limit?: number;
}

interface RankingsResponseEntry {
  rank?: number;
  agent_name?: string;
  name?: string;
  elo?: number;
  calibration_score?: number;
  games_played?: number;
  debate_count?: number;
  total_debates?: number;
  matches?: number;
}

interface RankingsResponse {
  rankings?: RankingsResponseEntry[];
  agents?: RankingsResponseEntry[];
  leaderboard?: RankingsResponseEntry[];
}

interface LiveRankingRow {
  rank: number;
  agentName: string;
  elo: number;
  calibrationScore?: number;
  debateCount: number;
}

function normalizeRankings(response: RankingsResponse | null): LiveRankingRow[] {
  const rawEntries = response?.rankings ?? response?.agents ?? response?.leaderboard ?? [];

  const sortedEntries = [...rawEntries].sort((a, b) => {
    if (a.rank !== undefined && b.rank !== undefined && a.rank !== b.rank) {
      return a.rank - b.rank;
    }
    if (a.rank !== undefined) return -1;
    if (b.rank !== undefined) return 1;
    return (b.elo ?? 1500) - (a.elo ?? 1500);
  });

  return sortedEntries.map((entry, index) => ({
    rank: entry.rank ?? index + 1,
    agentName: entry.agent_name ?? entry.name ?? 'Unknown agent',
    elo: Math.round(entry.elo ?? 1500),
    calibrationScore: entry.calibration_score,
    debateCount:
      entry.games_played ?? entry.debate_count ?? entry.total_debates ?? entry.matches ?? 0,
  }));
}

function formatErrorMessage(status: number | null): string {
  if (status === 401 || status === 403) return 'Authentication required to load live rankings.';
  if (status === 404) return 'The live rankings endpoint is unavailable.';
  return 'Failed to load live rankings.';
}

function LiveEloRankingsPanelComponent({ apiBase, limit = 20 }: LiveEloRankingsPanelProps) {
  const { tokens } = useAuth();
  const [response, setResponse] = useState<RankingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadRankings() {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams({ limit: String(limit) });
      const headers: HeadersInit = { 'Content-Type': 'application/json' };

      if (tokens?.access_token) {
        headers.Authorization = `Bearer ${tokens.access_token}`;
      }

      try {
        const res = await fetch(`${apiBase}/api/v1/agents/rankings?${params}`, {
          headers,
          signal: controller.signal,
        });

        if (!res.ok) {
          setResponse(null);
          setError(formatErrorMessage(res.status));
          return;
        }

        const data = (await res.json()) as RankingsResponse;
        setResponse(data);
      } catch (err) {
        if (controller.signal.aborted) return;
        setResponse(null);
        setError(err instanceof Error ? err.message : 'Failed to load live rankings.');
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void loadRankings();

    return () => controller.abort();
  }, [apiBase, limit, tokens?.access_token]);

  const rankings = useMemo(() => normalizeRankings(response), [response]);

  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h4 className="font-theme-data text-xs text-[var(--accent)]">Live Agent Rankings</h4>
          <p className="font-theme-data text-[11px] text-text-muted">
            Source: <span className="text-text">/api/v1/agents/rankings</span>
          </p>
        </div>
        {!loading && rankings.length > 0 && (
          <span className="font-theme-data text-[11px] text-text-muted">
            {rankings.length} agents
          </span>
        )}
      </div>

      {loading && (
        <div className="space-y-2 animate-pulse">
          {[1, 2, 3, 4, 5].map((item) => (
            <div key={item} className="h-10 bg-surface rounded" />
          ))}
        </div>
      )}

      {error && !loading && (
        <div className="rounded border border-red-500/40 bg-red-900/20 p-3">
          <p className="font-theme-data text-xs text-red-300">{error}</p>
        </div>
      )}

      {!loading && !error && rankings.length === 0 && (
        <p className="py-4 text-center font-theme-data text-xs text-text-muted">
          No live rankings are available yet.
        </p>
      )}

      {!loading && !error && rankings.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-theme-data">
            <thead>
              <tr className="border-b border-border text-text-muted">
                <th className="w-8 py-1.5 px-1 text-left">#</th>
                <th className="py-1.5 px-1 text-left">Agent</th>
                <th className="py-1.5 px-1 text-right">ELO</th>
                <th className="py-1.5 px-1 text-right">Calibration</th>
                <th className="py-1.5 px-1 text-right">Debates</th>
              </tr>
            </thead>
            <tbody>
              {rankings.map((agent) => {
                const calibrationScore = agent.calibrationScore ?? null;

                return (
                  <tr
                    key={agent.agentName}
                    className="border-b border-border/50 transition-colors hover:bg-surface/50"
                  >
                    <td className="py-1.5 px-1">
                      <div
                        className={`flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-bold ${getRankBadge(agent.rank)}`}
                      >
                        {agent.rank}
                      </div>
                    </td>
                    <td className="py-1.5 px-1">
                      <Link
                        href={`/agent/${encodeURIComponent(agent.agentName)}/`}
                        className="text-text transition-colors hover:text-accent"
                        title="View agent profile"
                      >
                        {agent.agentName}
                      </Link>
                    </td>
                    <td className={`py-1.5 px-1 text-right font-bold ${getEloColor(agent.elo)}`}>
                      {agent.elo}
                    </td>
                    <td className="py-1.5 px-1 text-right">
                      {calibrationScore !== null ? (
                        <span className={getConsistencyColor(calibrationScore)}>
                          {(calibrationScore * 100).toFixed(0)}%
                        </span>
                      ) : (
                        <span className="text-text-muted">--</span>
                      )}
                    </td>
                    <td className="py-1.5 px-1 text-right text-text-muted">{agent.debateCount}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export const LiveEloRankingsPanel = memo(LiveEloRankingsPanelComponent);
