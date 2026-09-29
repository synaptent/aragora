'use client';

import { useExecutionTimeline } from '@/hooks/useSelfImproveDetails';

const STATUS_COLORS: Record<string, string> = {
  active: 'text-amber-400 border-amber-400/40',
  testing: 'text-blue-400 border-blue-400/40',
  merged: 'text-emerald-400 border-emerald-400/40',
  rejected: 'text-red-400 border-red-400/40',
};

export function ExecutionTimeline() {
  const { branches, mergeDecisions, activeCount, loading } = useExecutionTimeline();

  if (loading)
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading execution timeline...
      </div>
    );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 font-theme-data text-xs text-[var(--text-muted)]">
        <span>
          Active branches: <span className="text-[var(--acid-green)]">{activeCount}</span>
        </span>
        <span>Total: {branches.length}</span>
      </div>

      {branches.length === 0 ? (
        <div className="text-[var(--text-muted)] font-theme-data text-sm p-4">
          No branch activity yet.
        </div>
      ) : (
        <div className="relative pl-6 space-y-3">
          <div className="absolute left-2 top-0 bottom-0 w-px bg-[var(--acid-green)]/20" />
          {branches.map((b, i) => (
            <div key={b.branch_name || i} className="relative card p-3">
              <div className="absolute -left-[22px] top-3 w-3 h-3 rounded-full border-2 border-[var(--acid-green)] bg-[var(--bg)]" />
              <div className="flex items-center justify-between mb-1">
                <span className="font-theme-data text-xs text-[var(--acid-green)]">
                  {b.branch_name}
                </span>
                <span
                  className={`text-[10px] font-theme-data px-2 py-0.5 border rounded ${STATUS_COLORS[b.status] || ''}`}
                >
                  {b.status.toUpperCase()}
                </span>
              </div>
              <p className="text-xs font-theme-data text-[var(--text-muted)]">{b.subtask}</p>
              <p className="text-[10px] font-theme-data text-[var(--text-muted)] mt-1">
                {b.created_at}
              </p>
            </div>
          ))}
        </div>
      )}

      {mergeDecisions.length > 0 && (
        <div className="space-y-2 mt-4">
          <h4 className="font-theme-data text-xs text-[var(--text-muted)] uppercase tracking-wider">
            Merge Decisions
          </h4>
          {mergeDecisions.map((d, i) => (
            <div key={i} className="card p-3 flex items-center justify-between">
              <span className="font-theme-data text-xs">{d.branch}</span>
              <span
                className={`text-[10px] font-theme-data px-2 py-0.5 border rounded ${d.decision === 'merged' ? 'text-emerald-400 border-emerald-400/40' : 'text-red-400 border-red-400/40'}`}
              >
                {d.decision.toUpperCase()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
