'use client';

export default function WorkflowsLoading() {
  return (
    <div
      className="min-h-screen bg-background p-4 sm:p-6"
      role="status"
      aria-label="Loading workflows"
    >
      {/* Header skeleton */}
      <div className="mb-6">
        <div className="h-8 w-48 bg-surface animate-pulse rounded mb-2" />
        <div className="h-4 w-96 bg-surface/60 animate-pulse rounded" />
      </div>

      {/* Workflow cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="border border-[var(--accent)]/20 rounded-lg p-4 bg-surface">
            {/* Card header */}
            <div className="flex items-center justify-between mb-3">
              <div className="h-5 w-32 bg-[var(--accent)]/20 animate-pulse rounded" />
              <div className="h-4 w-16 bg-[var(--accent)]/10 animate-pulse rounded" />
            </div>

            {/* Card content */}
            <div className="space-y-2 mb-4">
              <div className="h-3 w-full bg-surface/80 animate-pulse rounded" />
              <div className="h-3 w-3/4 bg-surface/80 animate-pulse rounded" />
            </div>

            {/* Workflow steps preview */}
            <div className="flex items-center gap-2 mb-4">
              {Array.from({ length: 4 }).map((_, j) => (
                <div key={j} className="w-8 h-8 rounded-full bg-[var(--accent)]/10 animate-pulse" />
              ))}
              <div className="flex-1 h-0.5 bg-[var(--accent)]/10 animate-pulse" />
            </div>

            {/* Card footer */}
            <div className="flex items-center justify-between pt-3 border-t border-[var(--accent)]/10">
              <div className="h-4 w-20 bg-surface/80 animate-pulse rounded" />
              <div className="flex gap-2">
                <div className="h-6 w-16 bg-[var(--accent)]/20 animate-pulse rounded" />
                <div className="h-6 w-16 bg-surface/80 animate-pulse rounded" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Screen reader announcement */}
      <span className="sr-only">Loading workflow data...</span>
    </div>
  );
}
