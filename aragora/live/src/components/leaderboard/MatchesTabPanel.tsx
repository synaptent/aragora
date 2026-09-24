'use client';

import { memo } from 'react';
import { MatchesSkeleton } from '../Skeleton';
import type { Match } from './types';
import { formatEloChange } from './types';

interface MatchesTabPanelProps {
  matches: Match[];
  loading: boolean;
}

function MatchesTabPanelComponent({ matches, loading }: MatchesTabPanelProps) {
  return (
    <div
      id="matches-panel"
      role="tabpanel"
      aria-labelledby="matches-tab"
      className="space-y-2 max-h-80 overflow-y-auto"
    >
      {loading && <MatchesSkeleton count={3} />}

      {!loading && matches.length === 0 && (
        <div className="text-center text-text-muted py-4">
          No matches yet. Run debate cycles to see match history.
        </div>
      )}

      {matches.map((match) => (
        <div key={match.debate_id} className="p-2 bg-bg border border-border rounded-lg">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-medium text-green-400">{match.winner} wins</span>
            {match.domain && (
              <span className="px-1.5 py-0.5 text-xs bg-surface rounded text-text-muted">
                {match.domain}
              </span>
            )}
          </div>

          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(match.elo_changes).map(([agent, change]) => (
              <span key={agent} className={`${change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {agent}: {formatEloChange(change)}
              </span>
            ))}
          </div>

          <div className="text-xs text-text-muted mt-1">
            {new Date(match.created_at).toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}

export const MatchesTabPanel = memo(MatchesTabPanelComponent);
