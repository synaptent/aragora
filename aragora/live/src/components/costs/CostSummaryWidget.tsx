'use client';

import Link from 'next/link';
import { useCostSummary } from '@/hooks/useCosts';

function formatCurrency(amount: number): string {
  if (amount >= 1000) return `$${(amount / 1000).toFixed(1)}k`;
  if (amount >= 1) return `$${amount.toFixed(2)}`;
  return `$${amount.toFixed(3)}`;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return n.toString();
}

/**
 * Compact cost summary widget for the executive dashboard.
 * Shows total spend, budget utilization, and API call count.
 */
export function CostSummaryWidget() {
  const { summary, isLoading, error } = useCostSummary('30d');

  if (isLoading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4 animate-pulse">
        <div className="h-4 bg-[var(--bg)] rounded w-1/3 mb-3" />
        <div className="h-8 bg-[var(--bg)] rounded w-1/2 mb-2" />
        <div className="h-3 bg-[var(--bg)] rounded w-full" />
      </div>
    );
  }

  if (error || !summary) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} COSTS</h3>
          <Link
            href="/usage"
            className="text-[10px] font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
          >
            VIEW
          </Link>
        </div>
        <p className="text-xs font-theme-data text-[var(--text-muted)]">Cost data unavailable</p>
      </div>
    );
  }

  const budgetPercent =
    summary.budget_usd > 0 ? Math.min((summary.total_cost_usd / summary.budget_usd) * 100, 100) : 0;

  const barColor =
    budgetPercent > 90
      ? 'bg-red-400'
      : budgetPercent > 75
        ? 'bg-yellow-400'
        : 'bg-[var(--acid-green)]';

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} COST OVERVIEW</h3>
        <Link
          href="/usage"
          className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
        >
          DETAILS
        </Link>
      </div>

      <div className="p-4 space-y-4">
        {/* Total spend + budget */}
        <div className="flex items-end justify-between">
          <div>
            <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
              30-day spend
            </div>
            <div className="text-xl font-theme-data text-[var(--text)] font-bold">
              {formatCurrency(summary.total_cost_usd)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
              of {formatCurrency(summary.budget_usd)} budget
            </div>
            <div
              className={`text-sm font-theme-data font-bold ${
                budgetPercent > 90
                  ? 'text-red-400'
                  : budgetPercent > 75
                    ? 'text-yellow-400'
                    : 'text-[var(--acid-green)]'
              }`}
            >
              {budgetPercent.toFixed(0)}%
            </div>
          </div>
        </div>

        {/* Budget bar */}
        <div className="w-full h-2 bg-[var(--bg)] rounded-full overflow-hidden">
          <div
            className={`h-full ${barColor} transition-all duration-500`}
            style={{ width: `${budgetPercent}%` }}
          />
        </div>

        {/* Quick stats */}
        <div className="grid grid-cols-3 gap-3 pt-2 border-t border-[var(--border)]">
          <div>
            <div className="text-[10px] font-theme-data text-[var(--text-muted)]">API Calls</div>
            <div className="text-sm font-theme-data text-[var(--text)]">
              {formatNumber(summary.api_calls)}
            </div>
          </div>
          <div>
            <div className="text-[10px] font-theme-data text-[var(--text-muted)]">Tokens In</div>
            <div className="text-sm font-theme-data text-[var(--text)]">
              {formatNumber(summary.tokens_in)}
            </div>
          </div>
          <div>
            <div className="text-[10px] font-theme-data text-[var(--text-muted)]">Tokens Out</div>
            <div className="text-sm font-theme-data text-[var(--text)]">
              {formatNumber(summary.tokens_out)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
