'use client';

import { useMemo, useState, useCallback } from 'react';
import { DeliberationCard, type Deliberation, type DeliberationStatus } from './DeliberationCard';

export interface DeliberationTrackerProps {
  /** List of debate sessions to display */
  deliberations: Deliberation[];
  /** Show filter tabs */
  showFilters?: boolean;
  /** Maximum decisionmaking sessions to show per section */
  maxVisible?: number;
  /** Callback when a deliberation is clicked */
  onDeliberationClick?: (deliberation: Deliberation) => void;
  /** Callback to view all decisionmaking sessions */
  onViewAll?: () => void;
  /** Additional className */
  className?: string;
  /** Title for the tracker */
  title?: string;
}

type FilterTab = 'all' | 'active' | 'completed' | 'failed';

const filterTabs: { id: FilterTab; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'active', label: 'Active' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
];

const statusToFilter: Record<DeliberationStatus, FilterTab> = {
  pending: 'active',
  in_progress: 'active',
  consensus_reached: 'completed',
  no_consensus: 'completed',
  failed: 'failed',
  timeout: 'failed',
};

/**
 * Debate Tracker - Panel showing active and recent sessions.
 *
 * Displays:
 * - Count of in-progress debates
 * - Round progress bars
 * - Participating agents
 * - Consensus status
 */
export function DeliberationTracker({
  deliberations,
  showFilters = true,
  maxVisible = 10,
  onDeliberationClick,
  onViewAll,
  className = '',
  title = 'Active Debates',
}: DeliberationTrackerProps) {
  const [activeFilter, setActiveFilter] = useState<FilterTab>('all');

  // Calculate stats
  const stats = useMemo(() => {
    const active = deliberations.filter(
      (d) => d.status === 'pending' || d.status === 'in_progress',
    ).length;
    const consensus = deliberations.filter((d) => d.status === 'consensus_reached').length;
    const noConsensus = deliberations.filter((d) => d.status === 'no_consensus').length;
    const failed = deliberations.filter(
      (d) => d.status === 'failed' || d.status === 'timeout',
    ).length;
    const slaViolations = deliberations.filter((d) => d.sla_status === 'violated').length;

    return { active, consensus, noConsensus, failed, slaViolations, total: deliberations.length };
  }, [deliberations]);

  // Filter decisionmaking sessions
  const filteredDeliberations = useMemo(() => {
    if (activeFilter === 'all') return deliberations;

    return deliberations.filter((d) => statusToFilter[d.status] === activeFilter);
  }, [deliberations, activeFilter]);

  // Sort: active first, then by start time
  const sortedDeliberations = useMemo(() => {
    return [...filteredDeliberations].sort((a, b) => {
      // Active sessions first
      const aActive = a.status === 'in_progress' || a.status === 'pending';
      const bActive = b.status === 'in_progress' || b.status === 'pending';
      if (aActive && !bActive) return -1;
      if (!aActive && bActive) return 1;

      // Then by start time (newest first)
      const aTime = a.started_at ? new Date(a.started_at).getTime() : 0;
      const bTime = b.started_at ? new Date(b.started_at).getTime() : 0;
      return bTime - aTime;
    });
  }, [filteredDeliberations]);

  const visibleDeliberations = useMemo(() => {
    return sortedDeliberations.slice(0, maxVisible);
  }, [sortedDeliberations, maxVisible]);

  const handleFilterClick = useCallback((filter: FilterTab) => {
    setActiveFilter(filter);
  }, []);

  // Get filter counts for badges
  const filterCounts: Record<FilterTab, number> = useMemo(() => {
    return {
      all: deliberations.length,
      active: stats.active,
      completed: stats.consensus + stats.noConsensus,
      failed: stats.failed,
    };
  }, [deliberations.length, stats]);

  return (
    <div className={`card ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            {stats.active > 0 && (
              <span className="w-2 h-2 rounded-full bg-[var(--acid-cyan)] animate-pulse" />
            )}
            <h3 className="font-theme-data text-sm text-[var(--accent)]">{title}</h3>
            <span className="text-xs text-text-muted font-theme-data">({stats.active} active)</span>
          </div>

          {onViewAll && (
            <button
              onClick={onViewAll}
              className="text-xs text-text-muted hover:text-[var(--accent)] transition-colors font-theme-data"
            >
              View All &rarr;
            </button>
          )}
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-2 mb-3">
          <div className="bg-surface p-2 rounded text-center">
            <div className="text-lg font-theme-data text-[var(--acid-cyan)]">{stats.active}</div>
            <div className="text-xs text-text-muted">Active</div>
          </div>
          <div className="bg-surface p-2 rounded text-center">
            <div className="text-lg font-theme-data text-green-400">{stats.consensus}</div>
            <div className="text-xs text-text-muted">Consensus</div>
          </div>
          <div className="bg-surface p-2 rounded text-center">
            <div className="text-lg font-theme-data text-yellow-400">{stats.noConsensus}</div>
            <div className="text-xs text-text-muted">No Cons.</div>
          </div>
          <div className="bg-surface p-2 rounded text-center">
            <div className="text-lg font-theme-data text-[var(--crimson)]">{stats.failed}</div>
            <div className="text-xs text-text-muted">Failed</div>
          </div>
        </div>

        {/* SLA violations warning */}
        {stats.slaViolations > 0 && (
          <div className="flex items-center gap-2 p-2 bg-red-900/10 border border-red-800/30 rounded text-xs">
            <span className="text-[var(--crimson)]">\u26A0</span>
            <span className="text-[var(--crimson)] font-theme-data">
              {stats.slaViolations} SLA violation{stats.slaViolations > 1 ? 's' : ''}
            </span>
          </div>
        )}

        {/* Filter tabs */}
        {showFilters && (
          <div className="flex gap-2 mt-3">
            {filterTabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => handleFilterClick(tab.id)}
                className={`px-2 py-1 text-xs font-theme-data rounded transition-colors flex items-center gap-1 ${
                  activeFilter === tab.id
                    ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30'
                    : 'bg-surface text-text-muted hover:text-text border border-transparent'
                }`}
              >
                {tab.label}
                {filterCounts[tab.id] > 0 && (
                  <span className="px-1 py-0.5 bg-surface/50 rounded text-xs">
                    {filterCounts[tab.id]}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Debate list */}
      <div className="max-h-[500px] overflow-y-auto">
        {visibleDeliberations.length === 0 ? (
          <div className="p-6 text-center text-text-muted font-theme-data text-sm">
            No debate sessions to display
          </div>
        ) : (
          <div className="p-4 space-y-3">
            {visibleDeliberations.map((deliberation) => (
              <DeliberationCard
                key={deliberation.id}
                deliberation={deliberation}
                onClick={onDeliberationClick}
              />
            ))}

            {sortedDeliberations.length > maxVisible && (
              <div className="text-center pt-2">
                <span className="text-xs font-theme-data text-text-muted">
                  + {sortedDeliberations.length - maxVisible} more decisionmaking sessions
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default DeliberationTracker;
