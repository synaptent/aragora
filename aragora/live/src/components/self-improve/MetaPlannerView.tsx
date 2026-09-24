'use client';

import { useMetaPlannerGoals } from '@/hooks/useSelfImproveDetails';

export function MetaPlannerView() {
  const { goals, signals, enrichment: _enrichment, loading, error } = useMetaPlannerGoals();

  if (loading)
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading MetaPlanner goals...
      </div>
    );
  if (error) return <div className="p-4 text-red-400 font-theme-data">Failed to load goals</div>;

  return (
    <div className="space-y-4">
      {/* Signal indicators */}
      <div className="flex flex-wrap gap-2">
        {signals.map((s) => (
          <span
            key={s}
            className="px-2 py-0.5 text-[10px] font-theme-data border border-[var(--acid-green)]/30 text-[var(--acid-green)] rounded"
          >
            {s}
          </span>
        ))}
      </div>

      {/* Goal cards */}
      {goals.length === 0 ? (
        <div className="text-[var(--text-muted)] font-theme-data text-sm p-4">
          No goals currently prioritized. Run a self-improvement cycle to generate goals.
        </div>
      ) : (
        <div className="space-y-3">
          {goals.map((goal, i) => (
            <div key={goal.id || i} className="card p-4 space-y-2">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[var(--acid-green)] font-theme-data text-xs">#{i + 1}</span>
                  <span className="font-theme-data text-sm text-[var(--text)]">
                    {goal.description}
                  </span>
                </div>
                <span className="text-[10px] font-theme-data px-2 py-0.5 border rounded border-amber-400/40 text-amber-400">
                  {goal.track}
                </span>
              </div>
              <div className="flex items-center gap-4 text-xs font-theme-data text-[var(--text-muted)]">
                <span>
                  Confidence:{' '}
                  <span
                    className={
                      goal.confidence > 0.7
                        ? 'text-emerald-400'
                        : goal.confidence > 0.4
                          ? 'text-amber-400'
                          : 'text-red-400'
                    }
                  >
                    {(goal.confidence * 100).toFixed(0)}%
                  </span>
                </span>
                <span>Priority: {goal.priority}</span>
              </div>
              {goal.reasoning && (
                <details className="text-xs">
                  <summary className="text-[var(--text-muted)] font-theme-data cursor-pointer hover:text-[var(--acid-green)]">
                    Reasoning
                  </summary>
                  <p className="mt-1 text-[var(--text-muted)] font-theme-data pl-2 border-l border-[var(--acid-green)]/20">
                    {goal.reasoning}
                  </p>
                </details>
              )}
              <div className="flex flex-wrap gap-1">
                {goal.signals?.map((s) => (
                  <span
                    key={s}
                    className="px-1.5 py-0.5 text-[9px] font-theme-data bg-[var(--surface)] text-[var(--text-muted)] rounded"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
