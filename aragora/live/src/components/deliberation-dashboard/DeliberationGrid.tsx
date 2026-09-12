'use client';

import React from 'react';
import type { Deliberation } from './types';
import { DeliberationCard } from './DeliberationCard';

interface DeliberationGridProps {
  deliberations: Deliberation[];
  loading?: boolean;
  emptyMessage?: string;
}

export function DeliberationGrid({
  deliberations,
  loading = false,
  emptyMessage = 'No active debate sessions',
}: DeliberationGridProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-surface border border-[var(--accent)]/20 p-4 animate-pulse">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-2 h-2 rounded-full bg-[var(--accent)]/20" />
              <div className="w-12 h-3 bg-[var(--accent)]/20 rounded" />
            </div>
            <div className="h-10 bg-[var(--accent)]/10 rounded mb-3" />
            <div className="h-1 bg-bg rounded-full mb-3" />
            <div className="flex justify-between">
              <div className="w-16 h-3 bg-[var(--accent)]/10 rounded" />
              <div className="w-10 h-3 bg-[var(--accent)]/10 rounded" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (deliberations.length === 0) {
    return (
      <div className="bg-surface border border-[var(--accent)]/20 p-8 text-center">
        <div className="text-4xl mb-4 opacity-30">◎</div>
        <p className="text-text-muted font-theme-data text-sm">{emptyMessage}</p>
        <p className="text-text-muted font-theme-data text-xs mt-2">
          Start a new debate from the Arena or run a Gauntlet stress test
        </p>
      </div>
    );
  }

  // Sort decisionmaking sessions: active first, then by updated_at
  const sorted = [...deliberations].sort((a, b) => {
    const statusPriority = {
      active: 0,
      consensus_forming: 1,
      initializing: 2,
      complete: 3,
      failed: 4,
    };
    const aPriority = statusPriority[a.status] ?? 5;
    const bPriority = statusPriority[b.status] ?? 5;
    if (aPriority !== bPriority) return aPriority - bPriority;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {sorted.map((deliberation) => (
        <DeliberationCard key={deliberation.id} deliberation={deliberation} />
      ))}
    </div>
  );
}
