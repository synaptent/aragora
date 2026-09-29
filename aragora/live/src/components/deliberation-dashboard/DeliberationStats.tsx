'use client';

import React from 'react';
import type { DeliberationStats as Stats } from './types';

interface DeliberationStatsProps {
  stats: Stats | null;
  loading?: boolean;
}

export function DeliberationStats({ stats, loading = false }: DeliberationStatsProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-surface border border-[var(--accent)]/30 p-4 animate-pulse">
            <div className="w-20 h-3 bg-[var(--accent)]/20 rounded mb-2" />
            <div className="w-12 h-6 bg-[var(--accent)]/10 rounded" />
          </div>
        ))}
      </div>
    );
  }

  const displayStats = stats ?? {
    active_count: 0,
    completed_today: 0,
    average_consensus_time: 0,
    average_rounds: 0,
    top_agents: [],
  };

  const formatTime = (seconds: number): string => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
  };

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="text-xs font-theme-data text-text-muted mb-1 uppercase">Active</div>
        <div className="text-2xl font-theme-data text-[var(--accent)]">
          {displayStats.active_count}
        </div>
        <div className="text-xs font-theme-data text-text-muted mt-1">active debates</div>
      </div>

      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="text-xs font-theme-data text-text-muted mb-1 uppercase">Completed</div>
        <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
          {displayStats.completed_today}
        </div>
        <div className="text-xs font-theme-data text-text-muted mt-1">today</div>
      </div>

      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="text-xs font-theme-data text-text-muted mb-1 uppercase">Avg Time</div>
        <div className="text-2xl font-theme-data text-text">
          {formatTime(displayStats.average_consensus_time)}
        </div>
        <div className="text-xs font-theme-data text-text-muted mt-1">to consensus</div>
      </div>

      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="text-xs font-theme-data text-text-muted mb-1 uppercase">Avg Rounds</div>
        <div className="text-2xl font-theme-data text-[var(--acid-yellow)]">
          {displayStats.average_rounds.toFixed(1)}
        </div>
        <div className="text-xs font-theme-data text-text-muted mt-1">per debate</div>
      </div>
    </div>
  );
}
