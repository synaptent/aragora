'use client';

import { useState, useMemo } from 'react';
import type { UsageTrendPoint } from '@/hooks/useUsageDashboard';

type Metric = 'debates' | 'tokens' | 'cost_usd' | 'consensus_rate';

interface UsageTrendProps {
  data: UsageTrendPoint[];
  loading?: boolean;
}

const METRIC_CONFIG: Record<
  Metric,
  { label: string; color: string; barColor: string; format: (v: number) => string }
> = {
  debates: {
    label: 'DEBATES',
    color: 'text-green-400',
    barColor: 'bg-green-500',
    format: (v) => v.toString(),
  },
  tokens: {
    label: 'TOKENS',
    color: 'text-cyan-400',
    barColor: 'bg-cyan-500',
    format: (v) => {
      if (v >= 1000000) return `${(v / 1000000).toFixed(1)}M`;
      if (v >= 1000) return `${(v / 1000).toFixed(1)}K`;
      return v.toString();
    },
  },
  cost_usd: {
    label: 'COST',
    color: 'text-yellow-400',
    barColor: 'bg-yellow-500',
    format: (v) => `$${v >= 1000 ? (v / 1000).toFixed(1) + 'K' : v.toFixed(2)}`,
  },
  consensus_rate: {
    label: 'CONSENSUS',
    color: 'text-purple-400',
    barColor: 'bg-purple-500',
    format: (v) => `${(v * 100).toFixed(0)}%`,
  },
};

/**
 * Usage Trend component for the usage dashboard.
 * Displays a bar chart of usage metrics over time with metric selector.
 */
export function UsageTrend({ data, loading = false }: UsageTrendProps) {
  const [metric, setMetric] = useState<Metric>('debates');

  const config = METRIC_CONFIG[metric];

  const { maxValue, values } = useMemo(() => {
    if (!data || data.length === 0) return { maxValue: 1, values: [] };
    const vals = data.map((point) => ({ date: point.date, value: point[metric] }));
    const max = Math.max(...vals.map((v) => v.value), 1);
    return { maxValue: max, values: vals };
  }, [data, metric]);

  const formatDate = (dateStr: string): string => {
    const d = new Date(dateStr);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4 flex items-center gap-2">
          <span>~</span> USAGE TREND
        </h3>
        <div className="animate-pulse">
          <div className="flex items-end gap-1 h-32">
            {Array.from({ length: 14 }).map((_, i) => (
              <div
                key={i}
                className="flex-1 bg-[var(--border)] rounded-t"
                style={{ height: `${20 + Math.random() * 60}%` }}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] flex items-center gap-2">
          <span>~</span> USAGE TREND
        </h3>
        <div className="flex items-center gap-1">
          {(Object.keys(METRIC_CONFIG) as Metric[]).map((m) => (
            <button
              key={m}
              onClick={() => setMetric(m)}
              className={`px-2 py-1 text-[10px] font-theme-data border transition-colors ${
                metric === m
                  ? `bg-[var(--acid-green)]/20 ${METRIC_CONFIG[m].color} border-[var(--acid-green)]/50`
                  : 'bg-[var(--surface)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/30'
              }`}
            >
              {METRIC_CONFIG[m].label}
            </button>
          ))}
        </div>
      </div>

      {values.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-xs font-theme-data text-[var(--text-muted)]">
          No trend data available
        </div>
      ) : (
        <>
          {/* Summary line */}
          <div className="flex items-center gap-4 mb-3 text-xs font-theme-data">
            <div>
              <span className="text-[var(--text-muted)]">Current: </span>
              <span className={config.color}>
                {config.format(values[values.length - 1]?.value ?? 0)}
              </span>
            </div>
            <div>
              <span className="text-[var(--text-muted)]">Peak: </span>
              <span className={config.color}>{config.format(maxValue)}</span>
            </div>
            <div>
              <span className="text-[var(--text-muted)]">Avg: </span>
              <span className={config.color}>
                {config.format(values.reduce((sum, v) => sum + v.value, 0) / values.length)}
              </span>
            </div>
          </div>

          {/* Chart */}
          <div className="flex items-end gap-[2px] h-32">
            {values.map((point, i) => {
              const heightPercent = (point.value / maxValue) * 100;
              return (
                <div key={i} className="flex-1 group relative" style={{ height: '100%' }}>
                  <div
                    className={`absolute bottom-0 left-0 right-0 ${config.barColor} opacity-70 hover:opacity-100 transition-opacity rounded-t`}
                    style={{ height: `${Math.max(heightPercent, 2)}%` }}
                  />
                  {/* Tooltip */}
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10">
                    <div className="bg-[var(--bg)] border border-[var(--border)] px-2 py-1 text-[10px] font-theme-data whitespace-nowrap">
                      <div className={config.color}>{config.format(point.value)}</div>
                      <div className="text-[var(--text-muted)]">{formatDate(point.date)}</div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* X-axis labels */}
          <div className="flex justify-between mt-1 text-[10px] font-theme-data text-[var(--text-muted)]">
            <span>{formatDate(values[0]?.date ?? '')}</span>
            {values.length > 2 && (
              <span>{formatDate(values[Math.floor(values.length / 2)]?.date ?? '')}</span>
            )}
            <span>{formatDate(values[values.length - 1]?.date ?? '')}</span>
          </div>
        </>
      )}
    </div>
  );
}

export default UsageTrend;
