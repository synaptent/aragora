'use client';

import { useBudgetStatus } from '@/hooks/useSystemHealth';

export function BudgetTracker() {
  const { budget, isLoading } = useBudgetStatus();

  if (isLoading)
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading budget...
      </div>
    );
  if (!budget)
    return (
      <div className="text-[var(--text-muted)] font-theme-data text-sm p-4">
        Budget tracking not configured.
      </div>
    );

  const pct = Math.min(100, budget.utilization * 100);
  const barColor = pct > 80 ? 'bg-red-400' : pct > 60 ? 'bg-amber-400' : 'bg-emerald-400';

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-theme-data text-xs text-[var(--text-muted)]">Budget Utilization</span>
        <span className="font-theme-data text-sm text-[var(--acid-green)]">
          ${budget.spent.toFixed(2)} / ${budget.total_budget.toFixed(2)}
        </span>
      </div>
      <div className="h-2 bg-[var(--bg)] rounded overflow-hidden">
        <div className={`h-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      {budget.forecast && (
        <div className="flex items-center justify-between text-[10px] font-theme-data text-[var(--text-muted)]">
          <span>Forecast EOM: ${budget.forecast.eom.toFixed(2)}</span>
          <span>Trend: {budget.forecast.trend}</span>
        </div>
      )}
    </div>
  );
}
