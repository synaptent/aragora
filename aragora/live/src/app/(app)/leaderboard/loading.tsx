'use client';

export default function LeaderboardLoading() {
  return (
    <div
      className="min-h-screen bg-background p-4 sm:p-6"
      role="status"
      aria-label="Loading leaderboard"
    >
      {/* Header */}
      <div className="mb-6 text-center">
        <div className="h-10 w-64 bg-surface animate-pulse rounded mx-auto mb-2" />
        <div className="h-4 w-96 bg-surface/60 animate-pulse rounded mx-auto" />
      </div>

      {/* Top 3 podium */}
      <div className="flex justify-center items-end gap-4 mb-8">
        {/* 2nd place */}
        <div className="w-32 text-center">
          <div className="w-16 h-16 rounded-full bg-[var(--accent)]/20 animate-pulse mx-auto mb-2" />
          <div className="h-4 w-20 bg-surface animate-pulse rounded mx-auto mb-1" />
          <div className="h-24 bg-surface/60 animate-pulse rounded-t-lg" />
        </div>
        {/* 1st place */}
        <div className="w-32 text-center">
          <div className="w-20 h-20 rounded-full bg-[var(--accent)]/30 animate-pulse mx-auto mb-2" />
          <div className="h-5 w-24 bg-surface animate-pulse rounded mx-auto mb-1" />
          <div className="h-32 bg-[var(--accent)]/20 animate-pulse rounded-t-lg" />
        </div>
        {/* 3rd place */}
        <div className="w-32 text-center">
          <div className="w-14 h-14 rounded-full bg-[var(--accent)]/10 animate-pulse mx-auto mb-2" />
          <div className="h-4 w-18 bg-surface animate-pulse rounded mx-auto mb-1" />
          <div className="h-16 bg-surface/40 animate-pulse rounded-t-lg" />
        </div>
      </div>

      {/* Leaderboard table */}
      <div className="max-w-4xl mx-auto border border-[var(--accent)]/20 rounded-lg bg-surface overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-5 gap-4 p-4 bg-surface/50 border-b border-[var(--accent)]/10">
          {['Rank', 'Agent', 'ELO', 'Win Rate', 'Debates'].map((header, i) => (
            <div key={i} className="h-4 w-16 bg-[var(--accent)]/20 animate-pulse rounded" />
          ))}
        </div>

        {/* Table rows */}
        {Array.from({ length: 10 }).map((_, i) => (
          <div
            key={i}
            className="grid grid-cols-5 gap-4 p-4 border-b border-[var(--accent)]/10 last:border-0"
          >
            <div className="h-6 w-8 bg-[var(--accent)]/10 animate-pulse rounded" />
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-surface/80 animate-pulse" />
              <div className="h-4 w-24 bg-surface/80 animate-pulse rounded" />
            </div>
            <div className="h-4 w-12 bg-[var(--accent)]/20 animate-pulse rounded" />
            <div className="h-4 w-14 bg-surface/60 animate-pulse rounded" />
            <div className="h-4 w-10 bg-surface/60 animate-pulse rounded" />
          </div>
        ))}
      </div>

      {/* Screen reader announcement */}
      <span className="sr-only">Loading leaderboard data...</span>
    </div>
  );
}
