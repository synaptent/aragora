'use client';

import { memo } from 'react';
import Link from 'next/link';
import { LeaderboardSkeleton } from '../Skeleton';
import type { AgentReputation } from './types';

interface ReputationTabPanelProps {
  reputations: AgentReputation[];
  loading: boolean;
}

function ReputationTabPanelComponent({ reputations, loading }: ReputationTabPanelProps) {
  return (
    <div
      id="reputation-panel"
      role="tabpanel"
      aria-labelledby="reputation-tab"
      className="space-y-2 max-h-80 overflow-y-auto"
    >
      {loading && <LeaderboardSkeleton count={3} />}

      {!loading && reputations.length === 0 && (
        <div className="text-center text-text-muted py-4">
          No reputation data yet. Run debate cycles to build agent reputations.
        </div>
      )}

      {reputations.map((rep, index) => (
        <div
          key={rep.agent}
          className="flex items-center gap-3 p-2 bg-bg border border-border rounded-lg hover:border-accent/50 transition-colors"
        >
          {/* Rank */}
          <div className="w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold bg-surface text-text-muted">
            {index + 1}
          </div>

          {/* Agent Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <Link
                href={`/agent/${encodeURIComponent(rep.agent)}/`}
                className="text-sm font-medium text-text hover:text-accent transition-colors cursor-pointer"
                title="View agent profile"
              >
                {rep.agent}
              </Link>
              <span
                className={`text-sm font-theme-data font-bold ${
                  rep.score >= 0.7
                    ? 'text-green-400'
                    : rep.score >= 0.4
                      ? 'text-yellow-400'
                      : 'text-red-400'
                }`}
              >
                {((Number(rep.score) || 0) * 100).toFixed(0)}%
              </span>
            </div>
            <div className="flex gap-3 text-xs text-text-muted">
              <span title="Vote weight in consensus">
                Vote:{' '}
                <span className="text-text">{(Number(rep.vote_weight) || 0).toFixed(2)}x</span>
              </span>
              <span title="Proposal acceptance rate">
                Accept:{' '}
                <span className="text-text">
                  {((Number(rep.proposal_acceptance_rate) || 0) * 100).toFixed(0)}%
                </span>
              </span>
              <span title="Critique value score">
                Critique:{' '}
                <span className="text-text">{(Number(rep.critique_value) || 0).toFixed(2)}</span>
              </span>
            </div>
          </div>

          {/* Debates count */}
          <div className="text-xs text-text-muted">{rep.debates_participated} debates</div>
        </div>
      ))}
    </div>
  );
}

export const ReputationTabPanel = memo(ReputationTabPanelComponent);
