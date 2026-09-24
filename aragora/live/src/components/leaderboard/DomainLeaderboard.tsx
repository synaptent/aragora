'use client';

import { memo, useState, useMemo } from 'react';
import Link from 'next/link';
import { useDomainLeaderboard } from '@/hooks/useEloAnalytics';
import { getEloColor, getRankBadge } from './types';

const DOMAINS = [
  { key: null, label: 'Overall' },
  { key: 'technical', label: 'Technical' },
  { key: 'business', label: 'Business' },
  { key: 'creative', label: 'Creative' },
  { key: 'security', label: 'Security' },
] as const;

type DomainKey = (typeof DOMAINS)[number]['key'];

function DomainLeaderboardComponent() {
  const [selectedDomain, setSelectedDomain] = useState<DomainKey>(null);
  const { agents, isLoading, error } = useDomainLeaderboard(selectedDomain);

  // Compute trend indicators from agent data
  const rankedAgents = useMemo(() => {
    if (!agents || agents.length === 0) return [];
    return agents.map((agent, idx) => {
      // Derive trend from elo vs domain_elo delta, or default to stable
      const eloValue = selectedDomain && agent.domain_elo ? agent.domain_elo : agent.elo;
      const totalGames = (agent.wins || 0) + (agent.losses || 0) + (agent.draws || 0);
      const winRate =
        totalGames > 0 ? ((agent.wins || 0) / totalGames) * 100 : (agent.win_rate ?? 0);

      return {
        ...agent,
        rank: idx + 1,
        displayElo: Math.round(eloValue),
        totalGames: agent.games || totalGames,
        displayWinRate: Math.round(winRate),
      };
    });
  }, [agents, selectedDomain]);

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-theme-data text-xs text-[var(--accent)]">Domain Leaderboards</h4>
      </div>

      {/* Domain Tabs */}
      <div className="flex gap-1 mb-3 overflow-x-auto" role="tablist" aria-label="Domain filter">
        {DOMAINS.map(({ key, label }) => (
          <button
            key={label}
            onClick={() => setSelectedDomain(key)}
            role="tab"
            aria-selected={selectedDomain === key}
            className={`px-2.5 py-1 rounded text-xs font-theme-data transition-colors whitespace-nowrap ${
              selectedDomain === key
                ? 'bg-accent text-bg font-medium'
                : 'text-text-muted hover:text-text hover:bg-surface'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="space-y-2 animate-pulse">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-10 bg-surface rounded" />
          ))}
        </div>
      )}

      {/* Error State */}
      {error && !isLoading && (
        <p className="text-text-muted font-theme-data text-xs py-4 text-center">
          Unable to load domain leaderboard. The endpoint may be unavailable.
        </p>
      )}

      {/* Empty State */}
      {!isLoading && !error && rankedAgents.length === 0 && (
        <p className="text-text-muted font-theme-data text-xs py-4 text-center">
          No rankings available for this domain. Run debate cycles to generate data.
        </p>
      )}

      {/* Rankings Table */}
      {!isLoading && rankedAgents.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-theme-data">
            <thead>
              <tr className="text-text-muted border-b border-border">
                <th className="text-left py-1.5 px-1 w-8">#</th>
                <th className="text-left py-1.5 px-1">Agent</th>
                <th className="text-right py-1.5 px-1">ELO</th>
                <th className="text-right py-1.5 px-1 hidden sm:table-cell">Win Rate</th>
                <th className="text-right py-1.5 px-1 hidden sm:table-cell">Games</th>
                <th className="text-right py-1.5 px-1">W/L/D</th>
              </tr>
            </thead>
            <tbody>
              {rankedAgents.map((agent) => (
                <tr
                  key={agent.agent_name}
                  className="border-b border-border/50 hover:bg-surface/50 transition-colors"
                >
                  <td className="py-1.5 px-1">
                    <div
                      className={`w-5 h-5 flex items-center justify-center rounded-full text-[10px] font-bold border ${getRankBadge(agent.rank)}`}
                    >
                      {agent.rank}
                    </div>
                  </td>
                  <td className="py-1.5 px-1">
                    <Link
                      href={`/agent/${encodeURIComponent(agent.agent_name)}/`}
                      className="text-text hover:text-accent transition-colors"
                      title="View agent profile"
                    >
                      {agent.agent_name}
                    </Link>
                  </td>
                  <td
                    className={`py-1.5 px-1 text-right font-bold ${getEloColor(agent.displayElo)}`}
                  >
                    {agent.displayElo}
                  </td>
                  <td className="py-1.5 px-1 text-right text-text-muted hidden sm:table-cell">
                    {agent.displayWinRate}%
                  </td>
                  <td className="py-1.5 px-1 text-right text-text-muted hidden sm:table-cell">
                    {agent.totalGames}
                  </td>
                  <td className="py-1.5 px-1 text-right text-text-muted">
                    <span className="text-green-400">{agent.wins || 0}</span>/
                    <span className="text-red-400">{agent.losses || 0}</span>/
                    <span className="text-yellow-400">{agent.draws || 0}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export const DomainLeaderboard = memo(DomainLeaderboardComponent);
