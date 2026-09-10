'use client';

import { memo } from 'react';
import { StatsSkeleton } from '../Skeleton';
import type { RankingStats } from './types';

interface StatsTabPanelProps {
  stats: RankingStats | null;
  loading: boolean;
}

function StatsTabPanelComponent({ stats, loading }: StatsTabPanelProps) {
  return (
    <div
      id="stats-panel"
      role="tabpanel"
      aria-labelledby="stats-tab"
      className="space-y-3 max-h-80 overflow-y-auto"
    >
      {loading && <StatsSkeleton />}

      {!loading && !stats && (
        <div className="text-center text-text-muted py-4">
          No ranking stats yet. Run debates to generate statistics.
        </div>
      )}

      {stats && (
        <>
          {/* Key Metrics */}
          <div className="grid grid-cols-2 gap-2">
            <div className="p-3 bg-bg border border-border rounded-lg">
              <div className="text-xs text-text-muted">Mean ELO</div>
              <div className="text-xl font-bold text-accent">
                {stats.mean_elo != null ? (Number(stats.mean_elo) || 0).toFixed(0) : 'N/A'}
              </div>
            </div>
            <div className="p-3 bg-bg border border-border rounded-lg">
              <div className="text-xs text-text-muted">Median ELO</div>
              <div className="text-xl font-bold text-text">
                {stats.median_elo != null ? (Number(stats.median_elo) || 0).toFixed(0) : 'N/A'}
              </div>
            </div>
            <div className="p-3 bg-bg border border-border rounded-lg">
              <div className="text-xs text-text-muted">Total Agents</div>
              <div className="text-xl font-bold text-text">{stats.total_agents || 0}</div>
            </div>
            <div className="p-3 bg-bg border border-border rounded-lg">
              <div className="text-xs text-text-muted">Total Matches</div>
              <div className="text-xl font-bold text-text">{stats.total_matches || 0}</div>
            </div>
          </div>

          {/* Rating Distribution */}
          {stats.rating_distribution && Object.keys(stats.rating_distribution).length > 0 && (
            <div className="p-3 bg-bg border border-border rounded-lg">
              <div className="text-xs text-text-muted mb-2">Rating Distribution</div>
              <div className="space-y-1">
                {Object.entries(stats.rating_distribution)
                  .sort((a, b) => parseInt(b[0]) - parseInt(a[0]))
                  .map(([tier, count]) => (
                    <div key={tier} className="flex items-center gap-2">
                      <span className="text-xs text-text-muted w-16">{tier}+</span>
                      <div className="flex-1 h-2 bg-surface rounded">
                        <div
                          className="h-full bg-accent rounded"
                          style={{ width: `${Math.min((count / stats.total_agents) * 100, 100)}%` }}
                        />
                      </div>
                      <span className="text-xs text-text w-8 text-right">{count}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Trending Agents */}
          {((stats.trending_up && stats.trending_up.length > 0) ||
            (stats.trending_down && stats.trending_down.length > 0)) && (
            <div className="grid grid-cols-2 gap-2">
              {stats.trending_up && stats.trending_up.length > 0 && (
                <div className="p-3 bg-bg border border-border rounded-lg">
                  <div className="text-xs text-green-400 mb-1">Trending Up</div>
                  {stats.trending_up.slice(0, 3).map((agent) => (
                    <div key={agent} className="text-sm text-text truncate">
                      {agent}
                    </div>
                  ))}
                </div>
              )}
              {stats.trending_down && stats.trending_down.length > 0 && (
                <div className="p-3 bg-bg border border-border rounded-lg">
                  <div className="text-xs text-red-400 mb-1">Trending Down</div>
                  {stats.trending_down.slice(0, 3).map((agent) => (
                    <div key={agent} className="text-sm text-text truncate">
                      {agent}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export const StatsTabPanel = memo(StatsTabPanelComponent);
