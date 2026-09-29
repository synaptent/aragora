'use client';

import type { BudgetStatus as BudgetStatusType } from '@/hooks/useUsageDashboard';

interface BudgetStatusProps {
  budget: BudgetStatusType | null;
  loading?: boolean;
}

/**
 * Budget Status component for the usage dashboard.
 * Displays budget utilization, alerts, and projections.
 */
export function BudgetStatus({ budget, loading = false }: BudgetStatusProps) {
  const formatCurrency = (value: number): string => {
    if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
    return `$${value.toFixed(2)}`;
  };

  const _getAlertColor = (level: string): string => {
    switch (level) {
      case 'critical':
        return 'red';
      case 'warning':
        return 'yellow';
      default:
        return 'green';
    }
  };

  const getAlertBorderColor = (level: string): string => {
    switch (level) {
      case 'critical':
        return 'border-red-500/50';
      case 'warning':
        return 'border-yellow-500/50';
      default:
        return 'border-green-500/30';
    }
  };

  const getAlertBgColor = (level: string): string => {
    switch (level) {
      case 'critical':
        return 'bg-red-500/10';
      case 'warning':
        return 'bg-yellow-500/10';
      default:
        return 'bg-green-500/10';
    }
  };

  const getAlertTextColor = (level: string): string => {
    switch (level) {
      case 'critical':
        return 'text-red-400';
      case 'warning':
        return 'text-yellow-400';
      default:
        return 'text-green-400';
    }
  };

  const getUtilizationBarColor = (percent: number, alertLevel: string): string => {
    if (alertLevel === 'critical') return 'bg-red-500';
    if (alertLevel === 'warning') return 'bg-yellow-500';
    if (percent >= 80) return 'bg-yellow-500';
    return 'bg-green-500';
  };

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4 flex items-center gap-2">
          <span>$</span> BUDGET STATUS
        </h3>
        <div className="animate-pulse space-y-4">
          <div className="h-4 bg-[var(--border)] rounded w-full" />
          <div className="h-8 bg-[var(--border)] rounded w-3/4" />
          <div className="h-4 bg-[var(--border)] rounded w-1/2" />
        </div>
      </div>
    );
  }

  if (!budget) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4 flex items-center gap-2">
          <span>$</span> BUDGET STATUS
        </h3>
        <p className="text-xs font-theme-data text-[var(--text-muted)]">
          No budget data available. Configure budget limits in settings.
        </p>
      </div>
    );
  }

  return (
    <div className={`bg-[var(--surface)] border ${getAlertBorderColor(budget.alert_level)} p-4`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] flex items-center gap-2">
          <span>$</span> BUDGET STATUS
        </h3>
        {budget.alert_level !== 'normal' && (
          <span
            className={`px-2 py-1 text-xs font-theme-data uppercase ${getAlertBgColor(budget.alert_level)} ${getAlertTextColor(budget.alert_level)}`}
          >
            {budget.alert_level}
          </span>
        )}
      </div>

      {/* Budget Progress Bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs font-theme-data mb-2">
          <span className="text-[var(--text-muted)]">
            {formatCurrency(budget.spent_usd)} / {formatCurrency(budget.monthly_limit_usd)}
          </span>
          <span className={getAlertTextColor(budget.alert_level)}>
            {budget.utilization_percent.toFixed(1)}%
          </span>
        </div>
        <div className="h-3 bg-[var(--border)] rounded-full overflow-hidden">
          <div
            className={`h-full ${getUtilizationBarColor(budget.utilization_percent, budget.alert_level)} transition-all duration-500`}
            style={{ width: `${Math.min(budget.utilization_percent, 100)}%` }}
          />
        </div>
      </div>

      {/* Budget Details Grid */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">Remaining</div>
          <div
            className={`text-lg font-theme-data font-bold ${budget.remaining_usd > 0 ? 'text-green-400' : 'text-red-400'}`}
          >
            {formatCurrency(budget.remaining_usd)}
          </div>
        </div>
        <div>
          <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">Daily Average</div>
          <div className="text-lg font-theme-data font-bold text-[var(--acid-cyan)]">
            {formatCurrency(budget.daily_average_usd)}
          </div>
        </div>
        <div>
          <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">
            Days Remaining
          </div>
          <div className="text-lg font-theme-data font-bold text-yellow-400">
            {budget.days_remaining}
          </div>
        </div>
        <div>
          <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">
            EOM Projection
          </div>
          <div
            className={`text-lg font-theme-data font-bold ${budget.will_exceed ? 'text-red-400' : 'text-green-400'}`}
          >
            {formatCurrency(budget.projected_end_of_month_usd)}
          </div>
        </div>
      </div>

      {/* Warning/Alert Message */}
      {budget.will_exceed && (
        <div
          className={`p-3 ${getAlertBgColor(budget.alert_level)} border ${getAlertBorderColor(budget.alert_level)}`}
        >
          <div className={`text-xs font-theme-data ${getAlertTextColor(budget.alert_level)}`}>
            {'!'} WARNING: Projected to exceed budget by{' '}
            {formatCurrency(budget.projected_end_of_month_usd - budget.monthly_limit_usd)}
          </div>
          <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
            Consider reducing usage or increasing budget limit.
          </div>
        </div>
      )}

      {/* Budget is healthy */}
      {!budget.will_exceed && budget.alert_level === 'normal' && (
        <div className="p-3 bg-green-500/10 border border-green-500/30">
          <div className="text-xs font-theme-data text-green-400">
            {'>'} Budget on track. {budget.days_remaining} days remaining at current rate.
          </div>
        </div>
      )}
    </div>
  );
}

export default BudgetStatus;
