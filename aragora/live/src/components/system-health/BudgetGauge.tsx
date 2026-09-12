'use client';

import { useBudgetStatus } from '@/hooks/useSystemHealth';

const TREND_ICON: Record<string, string> = { increasing: '↗', stable: '→', decreasing: '↘' };

const TREND_COLOR: Record<string, string> = {
  increasing: 'text-acid-red',
  stable: 'text-[var(--accent)]',
  decreasing: 'text-[var(--acid-cyan)]',
};

export function BudgetGauge() {
  const { budget, isLoading, available } = useBudgetStatus();

  if (isLoading) {
    return (
      <div className="card p-6 animate-pulse">
        <div className="h-4 bg-surface rounded w-36 mb-4" />
        <div className="h-8 bg-surface rounded" />
      </div>
    );
  }

  if (!available || !budget) {
    return (
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Budget Utilization</h3>
        <p className="text-text-muted font-theme-data text-xs">Budget tracking unavailable</p>
      </div>
    );
  }

  const pct = Math.min(budget.utilization * 100, 100);
  const barColor =
    budget.utilization > 0.95
      ? 'bg-acid-red'
      : budget.utilization > 0.8
        ? 'bg-acid-yellow'
        : 'bg-[var(--accent)]';
  const pctColor =
    budget.utilization > 0.95
      ? 'text-acid-red'
      : budget.utilization > 0.8
        ? 'text-[var(--acid-yellow)]'
        : 'text-[var(--accent)]';

  return (
    <div className="card p-6">
      <h3 className="font-theme-data text-[var(--accent)] mb-4">Budget Utilization</h3>

      {/* Big percentage */}
      <div className="flex items-end gap-2 mb-4">
        <span className={`font-theme-data text-3xl font-bold ${pctColor}`}>{pct.toFixed(1)}%</span>
        <span className="font-theme-data text-xs text-text-muted mb-1">utilized</span>
      </div>

      {/* Progress bar */}
      <div className="h-4 bg-surface rounded overflow-hidden border border-border mb-3 relative">
        <div
          className={`h-full ${barColor} transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
        {/* Forecast marker */}
        {budget.forecast && budget.total_budget > 0 && (
          <div
            className="absolute top-0 h-full w-0.5 bg-text-muted/60"
            style={{ left: `${Math.min((budget.forecast.eom / budget.total_budget) * 100, 100)}%` }}
            title={`EOM forecast: $${budget.forecast.eom.toFixed(2)}`}
          />
        )}
      </div>

      {/* Spent / Total */}
      <div className="flex justify-between font-theme-data text-xs mb-3">
        <span className="text-text">
          ${budget.spent.toFixed(2)} <span className="text-text-muted">spent</span>
        </span>
        <span className="text-text-muted">${budget.total_budget.toFixed(2)} budget</span>
      </div>

      {/* Forecast */}
      {budget.forecast && (
        <div className="flex items-center gap-2 font-theme-data text-xs border-t border-border pt-3">
          <span className="text-text-muted">EOM Forecast:</span>
          <span className="text-text">${budget.forecast.eom.toFixed(2)}</span>
          <span className={TREND_COLOR[budget.forecast.trend] || 'text-text-muted'}>
            {TREND_ICON[budget.forecast.trend] || ''} {budget.forecast.trend}
          </span>
        </div>
      )}
    </div>
  );
}
