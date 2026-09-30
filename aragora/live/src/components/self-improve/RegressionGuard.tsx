'use client';

import { useMetricsComparison } from '@/hooks/useSelfImproveDetails';

export function RegressionGuard() {
  const { comparisons, regressions, overallHealth, loading } = useMetricsComparison();

  if (loading)
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading metrics...
      </div>
    );

  const healthColor =
    overallHealth === 'improved'
      ? 'text-emerald-400'
      : overallHealth === 'degraded'
        ? 'text-red-400'
        : 'text-amber-400';

  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-center justify-between">
        <span className="font-theme-data text-xs text-[var(--text-muted)]">Overall Health</span>
        <span className={`font-theme-data text-sm font-bold ${healthColor}`}>
          {overallHealth.toUpperCase()}
        </span>
      </div>

      {regressions.length > 0 && (
        <div className="card p-4 border border-red-400/30 space-y-2">
          <h4 className="font-theme-data text-xs text-red-400 uppercase tracking-wider">
            Regressions Detected
          </h4>
          {regressions.map((r, i) => (
            <div key={i} className="flex items-center justify-between text-xs font-theme-data">
              <span className="text-[var(--text)]">{r.metric_name}</span>
              <div className="flex items-center gap-2">
                <span className="text-[var(--text-muted)]">{r.before.toFixed(2)}</span>
                <span className="text-red-400">&rarr;</span>
                <span className="text-red-400">{r.after.toFixed(2)}</span>
                <span className="text-red-400 text-[10px]">
                  ({r.delta > 0 ? '+' : ''}
                  {r.delta.toFixed(2)})
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {comparisons.length > 0 && (
        <div className="space-y-2">
          <h4 className="font-theme-data text-xs text-[var(--text-muted)] uppercase tracking-wider">
            All Metrics
          </h4>
          {comparisons.map((c, i) => (
            <div key={i} className="card p-3 flex items-center justify-between">
              <span className="font-theme-data text-xs text-[var(--text)]">{c.metric_name}</span>
              <div className="flex items-center gap-2 text-xs font-theme-data">
                <span className="text-[var(--text-muted)]">{c.before.toFixed(2)}</span>
                <span className={c.is_regression ? 'text-red-400' : 'text-emerald-400'}>
                  &rarr;
                </span>
                <span className={c.is_regression ? 'text-red-400' : 'text-emerald-400'}>
                  {c.after.toFixed(2)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {comparisons.length === 0 && regressions.length === 0 && (
        <p className="text-[var(--text-muted)] font-theme-data text-sm p-4">
          No metrics comparisons available. Complete a self-improvement cycle to generate data.
        </p>
      )}
    </div>
  );
}
