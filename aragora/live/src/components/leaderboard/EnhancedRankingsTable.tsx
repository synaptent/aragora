'use client';

import { memo, useMemo, useState, useCallback } from 'react';
import Link from 'next/link';
import type { AgentRanking } from './types';
import { getEloColor, getRankBadge, getConsistencyColor } from './types';

type SortField = 'elo' | 'win_rate' | 'games' | 'consistency';
type SortDir = 'asc' | 'desc';

interface EnhancedRankingsTableProps {
  agents: AgentRanking[];
  loading: boolean;
  error: string | null;
  endpointErrors: Record<string, string>;
}

/** Derive a trend class from win_rate and elo.
 *  >55% win rate and elo >= 1500 => rising
 *  <45% win rate or elo < 1400 => falling
 *  Otherwise => stable
 */
function getTrend(agent: AgentRanking): 'up' | 'down' | 'stable' {
  const wr = agent.win_rate ?? 0;
  if (wr > 55 && agent.elo >= 1500) return 'up';
  if (wr < 45 || agent.elo < 1400) return 'down';
  return 'stable';
}

const TREND_ICON: Record<string, { char: string; color: string }> = {
  up: { char: '\u25B2', color: 'text-green-400' }, // Black up triangle
  down: { char: '\u25BC', color: 'text-red-400' }, // Black down triangle
  stable: { char: '\u25C6', color: 'text-text-muted' }, // Black diamond
};

function EnhancedRankingsTableComponent({
  agents,
  loading,
  error,
  endpointErrors,
}: EnhancedRankingsTableProps) {
  const [sortField, setSortField] = useState<SortField>('elo');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const handleSort = useCallback(
    (field: SortField) => {
      if (sortField === field) {
        setSortDir((prev) => (prev === 'desc' ? 'asc' : 'desc'));
      } else {
        setSortField(field);
        setSortDir('desc');
      }
    },
    [sortField],
  );

  const sortedAgents = useMemo(() => {
    if (!agents || agents.length === 0) return [];

    const sorted = [...agents].sort((a, b) => {
      let aVal: number;
      let bVal: number;

      switch (sortField) {
        case 'elo':
          aVal = a.elo;
          bVal = b.elo;
          break;
        case 'win_rate':
          aVal = a.win_rate;
          bVal = b.win_rate;
          break;
        case 'games':
          aVal = a.games;
          bVal = b.games;
          break;
        case 'consistency':
          aVal = Number(a.consistency) || 0;
          bVal = Number(b.consistency) || 0;
          break;
        default:
          return 0;
      }

      return sortDir === 'desc' ? bVal - aVal : aVal - bVal;
    });

    return sorted;
  }, [agents, sortField, sortDir]);

  const SortHeader = ({
    field,
    label,
    className = '',
  }: {
    field: SortField;
    label: string;
    className?: string;
  }) => {
    const isActive = sortField === field;
    const arrow = isActive ? (sortDir === 'desc' ? ' \u2193' : ' \u2191') : '';

    return (
      <th
        className={`py-1.5 px-1 cursor-pointer select-none hover:text-text transition-colors ${
          isActive ? 'text-[var(--accent)]' : 'text-text-muted'
        } ${className}`}
        onClick={() => handleSort(field)}
        role="columnheader"
        aria-sort={isActive ? (sortDir === 'desc' ? 'descending' : 'ascending') : 'none'}
      >
        {label}
        {arrow}
      </th>
    );
  };

  if (loading) {
    return (
      <div className="space-y-2 animate-pulse">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-10 bg-surface rounded" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-500/40 rounded p-3 mb-2">
        <div className="text-red-300 text-sm font-medium mb-1">{error}</div>
        {Object.keys(endpointErrors).length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-red-200 hover:text-red-100">
              Show details
            </summary>
            <ul className="mt-2 space-y-1 text-red-200">
              {Object.entries(endpointErrors).map(([endpoint, msg]) => (
                <li key={endpoint}>
                  <span className="font-theme-data">{endpoint}:</span> {msg}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    );
  }

  if (sortedAgents.length === 0) {
    return (
      <div className="text-center text-text-muted py-4 font-theme-data text-sm">
        No rankings yet. Run debate cycles to generate rankings.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-theme-data" role="table">
        <thead>
          <tr className="border-b border-border">
            <th className="text-left py-1.5 px-1 text-text-muted w-8">#</th>
            <th className="text-left py-1.5 px-1 text-text-muted">Agent</th>
            <th className="text-center py-1.5 px-1 text-text-muted w-8">Trend</th>
            <SortHeader field="elo" label="ELO" className="text-right" />
            <SortHeader
              field="win_rate"
              label="Win %"
              className="text-right hidden sm:table-cell"
            />
            <SortHeader field="games" label="Games" className="text-right hidden sm:table-cell" />
            <SortHeader
              field="consistency"
              label="Calibration"
              className="text-right hidden md:table-cell"
            />
            <th className="text-right py-1.5 px-1 text-text-muted">W/L/D</th>
          </tr>
        </thead>
        <tbody>
          {sortedAgents.map((agent, idx) => {
            const trend = getTrend(agent);
            const trendInfo = TREND_ICON[trend];
            const rank = idx + 1;
            const consistency = Number(agent.consistency) || 0;

            return (
              <tr
                key={agent.name}
                className="border-b border-border/50 hover:bg-surface/50 transition-colors"
              >
                {/* Rank */}
                <td className="py-1.5 px-1">
                  <div
                    className={`w-5 h-5 flex items-center justify-center rounded-full text-[10px] font-bold border ${getRankBadge(rank)}`}
                  >
                    {rank}
                  </div>
                </td>

                {/* Agent Name + Model hint */}
                <td className="py-1.5 px-1">
                  <Link
                    href={`/agent/${encodeURIComponent(agent.name)}/`}
                    className="text-text hover:text-accent transition-colors"
                    title="View agent profile"
                  >
                    {agent.name}
                  </Link>
                </td>

                {/* Trend indicator */}
                <td className="py-1.5 px-1 text-center">
                  <span className={`text-[10px] ${trendInfo.color}`} title={`Trend: ${trend}`}>
                    {trendInfo.char}
                  </span>
                </td>

                {/* ELO */}
                <td className={`py-1.5 px-1 text-right font-bold ${getEloColor(agent.elo)}`}>
                  {agent.elo}
                </td>

                {/* Win Rate */}
                <td className="py-1.5 px-1 text-right text-text-muted hidden sm:table-cell">
                  {agent.win_rate}%
                </td>

                {/* Games */}
                <td className="py-1.5 px-1 text-right text-text-muted hidden sm:table-cell">
                  {agent.games}
                </td>

                {/* Calibration / Consistency */}
                <td className="py-1.5 px-1 text-right hidden md:table-cell">
                  {agent.consistency !== undefined ? (
                    <span
                      className={`${getConsistencyColor(consistency)} bg-surface px-1.5 py-0.5 rounded`}
                      title={`Calibration: ${(consistency * 100).toFixed(0)}%`}
                    >
                      {(consistency * 100).toFixed(0)}%
                    </span>
                  ) : (
                    <span className="text-text-muted">--</span>
                  )}
                </td>

                {/* W/L/D */}
                <td className="py-1.5 px-1 text-right text-text-muted">
                  <span className="text-green-400">{agent.wins}</span>/
                  <span className="text-red-400">{agent.losses}</span>/
                  <span className="text-yellow-400">{agent.draws}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export const EnhancedRankingsTable = memo(EnhancedRankingsTableComponent);
