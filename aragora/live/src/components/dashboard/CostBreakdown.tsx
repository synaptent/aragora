'use client';

import { useState } from 'react';
import type { CostBreakdown as CostBreakdownType } from '@/hooks/useUsageDashboard';

interface CostBreakdownProps {
  breakdown: CostBreakdownType | null;
  loading?: boolean;
}

const BAR_COLORS = [
  'bg-green-500',
  'bg-cyan-500',
  'bg-yellow-500',
  'bg-purple-500',
  'bg-red-500',
  'bg-blue-500',
  'bg-pink-500',
  'bg-orange-500',
];

const TEXT_COLORS = [
  'text-green-400',
  'text-cyan-400',
  'text-yellow-400',
  'text-purple-400',
  'text-red-400',
  'text-blue-400',
  'text-pink-400',
  'text-orange-400',
];

/**
 * Cost Breakdown component for the usage dashboard.
 * Displays cost distribution by agent and model with horizontal bar charts.
 */
export function CostBreakdown({ breakdown, loading = false }: CostBreakdownProps) {
  const [view, setView] = useState<'agent' | 'model'>('agent');

  const formatCurrency = (value: number): string => {
    if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
    return `$${value.toFixed(2)}`;
  };

  const formatNumber = (num: number): string => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4 flex items-center gap-2">
          <span>#</span> COST BREAKDOWN
        </h3>
        <div className="animate-pulse space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="space-y-1">
              <div className="h-3 bg-[var(--border)] rounded w-24" />
              <div
                className="h-5 bg-[var(--border)] rounded"
                style={{ width: `${90 - i * 15}%` }}
              />
            </div>
          ))}
        </div>
      </div>
    );
  }

  const items = view === 'agent' ? breakdown?.by_agent : breakdown?.by_model;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] flex items-center gap-2">
          <span>#</span> COST BREAKDOWN
        </h3>
        <div className="flex items-center gap-1">
          {(['agent', 'model'] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-2 py-1 text-[10px] font-theme-data border transition-colors ${
                view === v
                  ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/50'
                  : 'bg-[var(--surface)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/30'
              }`}
            >
              BY {v.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {!items || items.length === 0 ? (
        <p className="text-xs font-theme-data text-[var(--text-muted)]">
          No cost data available for the selected period.
        </p>
      ) : (
        <div className="space-y-3">
          {/* Total */}
          <div className="flex items-center justify-between text-xs font-theme-data pb-2 border-b border-[var(--border)]">
            <span className="text-[var(--text-muted)]">TOTAL</span>
            <span className="text-[var(--acid-green)] font-bold">
              {formatCurrency(breakdown?.total_cost_usd ?? 0)}
            </span>
          </div>

          {/* Bars */}
          {items.slice(0, 8).map((item, idx) => {
            const barColor = BAR_COLORS[idx % BAR_COLORS.length];
            const textColor = TEXT_COLORS[idx % TEXT_COLORS.length];

            return (
              <div key={item.name} className="space-y-1">
                <div className="flex items-center justify-between text-xs font-theme-data">
                  <span className={textColor}>{item.name}</span>
                  <span className="text-[var(--text-muted)]">
                    {formatCurrency(item.cost_usd)} ({item.percentage.toFixed(1)}%)
                  </span>
                </div>
                <div className="h-2 bg-[var(--border)] rounded-full overflow-hidden">
                  <div
                    className={`h-full ${barColor} transition-all duration-500`}
                    style={{ width: `${Math.min(item.percentage, 100)}%` }}
                  />
                </div>
                <div className="flex items-center gap-3 text-[10px] font-theme-data text-[var(--text-muted)]">
                  <span>{formatNumber(item.tokens)} tokens</span>
                  <span>{formatNumber(item.requests)} requests</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default CostBreakdown;
