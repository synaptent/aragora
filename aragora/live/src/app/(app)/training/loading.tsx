'use client';

export default function TrainingLoading() {
  return (
    <div
      className="min-h-screen bg-background p-4 sm:p-6"
      role="status"
      aria-label="Loading training dashboard"
    >
      {/* Header */}
      <div className="mb-6">
        <div className="h-8 w-56 bg-surface animate-pulse rounded mb-2" />
        <div className="h-4 w-80 bg-surface/60 animate-pulse rounded" />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="border border-[var(--accent)]/20 rounded-lg p-4 bg-surface">
            <div className="h-3 w-20 bg-[var(--accent)]/20 animate-pulse rounded mb-2" />
            <div className="h-8 w-16 bg-[var(--accent)]/30 animate-pulse rounded" />
          </div>
        ))}
      </div>

      {/* Training jobs table */}
      <div className="border border-[var(--accent)]/20 rounded-lg bg-surface overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-5 gap-4 p-4 bg-surface/50 border-b border-[var(--accent)]/10">
          {['Model', 'Status', 'Progress', 'Started', 'Actions'].map((header, i) => (
            <div key={i} className="h-4 w-16 bg-[var(--accent)]/20 animate-pulse rounded" />
          ))}
        </div>

        {/* Table rows */}
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="grid grid-cols-5 gap-4 p-4 border-b border-[var(--accent)]/10 last:border-0"
          >
            <div className="h-4 w-24 bg-surface/80 animate-pulse rounded" />
            <div className="h-4 w-16 bg-[var(--accent)]/10 animate-pulse rounded" />
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 bg-surface/80 animate-pulse rounded-full" />
              <div className="h-4 w-8 bg-surface/60 animate-pulse rounded" />
            </div>
            <div className="h-4 w-20 bg-surface/60 animate-pulse rounded" />
            <div className="flex gap-2">
              <div className="h-6 w-14 bg-[var(--accent)]/20 animate-pulse rounded" />
              <div className="h-6 w-14 bg-surface/80 animate-pulse rounded" />
            </div>
          </div>
        ))}
      </div>

      {/* Screen reader announcement */}
      <span className="sr-only">Loading training dashboard data...</span>
    </div>
  );
}
