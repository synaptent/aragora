'use client';

import { KPICard, KPIGrid, KPIMiniCard } from './KPICards';
import type { ROIAnalysis } from '@/hooks/useUsageDashboard';

interface ROIMetricsProps {
  roi: ROIAnalysis | null;
  loading?: boolean;
}

/**
 * ROI Metrics component for the usage dashboard.
 * Displays ROI percentage, time savings, cost savings, and industry benchmarks.
 */
export function ROIMetrics({ roi, loading = false }: ROIMetricsProps) {
  const formatCurrency = (value: number): string => {
    if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
    return `$${value.toFixed(0)}`;
  };

  const formatHours = (hours: number): string => {
    if (hours >= 1000) return `${(hours / 1000).toFixed(1)}K hrs`;
    return `${hours.toFixed(0)} hrs`;
  };

  const _getTrendDirection = (trend: string): 'up' | 'down' | 'neutral' => {
    if (trend === 'increasing' || trend === 'improving') return 'up';
    if (trend === 'decreasing' || trend === 'declining') return 'down';
    return 'neutral';
  };

  const getTrendColor = (trend: string): 'green' | 'red' | 'yellow' => {
    if (trend === 'increasing' || trend === 'improving') return 'green';
    if (trend === 'decreasing' || trend === 'declining') return 'red';
    return 'yellow';
  };

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-theme-data text-[var(--acid-green)] flex items-center gap-2">
        <span>$</span> ROI ANALYSIS
      </h3>

      {/* Primary ROI KPIs */}
      <KPIGrid columns={4}>
        <KPICard
          title="ROI"
          value={roi ? `${roi.roi_percentage.toFixed(0)}%` : '-'}
          subtitle={roi ? `${roi.benchmark.percentile}th percentile` : undefined}
          change={
            roi
              ? {
                  value: Math.abs(roi.roi_percentage - roi.benchmark.avg_roi),
                  direction: roi.roi_percentage >= roi.benchmark.avg_roi ? 'up' : 'down',
                  period: 'industry avg',
                }
              : undefined
          }
          color="green"
          loading={loading}
        />
        <KPICard
          title="Time Saved"
          value={roi ? formatHours(roi.time_saved_hours) : '-'}
          subtitle={roi ? `vs ${formatHours(roi.manual_equivalent_hours)} manual` : undefined}
          color="cyan"
          loading={loading}
        />
        <KPICard
          title="Cost Savings"
          value={roi ? formatCurrency(roi.cost_savings_usd) : '-'}
          subtitle={roi ? `${formatCurrency(roi.cost_per_decision)}/decision` : undefined}
          color="yellow"
          loading={loading}
        />
        <KPICard
          title="Value Generated"
          value={roi ? formatCurrency(roi.value_generated_usd) : '-'}
          subtitle="total value"
          color="purple"
          loading={loading}
        />
      </KPIGrid>

      {/* Trends and Benchmarks */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Trends */}
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <h4 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3 flex items-center gap-2">
            <span>~</span> TRENDS
          </h4>
          <div className="space-y-1">
            <KPIMiniCard
              label="ROI Trend"
              value={roi?.trends.roi_trend ?? '-'}
              color={roi ? getTrendColor(roi.trends.roi_trend) : 'yellow'}
            />
            <KPIMiniCard
              label="Efficiency Trend"
              value={roi?.trends.efficiency_trend ?? '-'}
              color={roi ? getTrendColor(roi.trends.efficiency_trend) : 'yellow'}
            />
          </div>
        </div>

        {/* Industry Benchmark */}
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <h4 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3 flex items-center gap-2">
            <span>#</span> INDUSTRY BENCHMARK
          </h4>
          <div className="space-y-1">
            <KPIMiniCard label="Industry" value={roi?.benchmark.industry ?? '-'} color="cyan" />
            <KPIMiniCard
              label="Avg Industry ROI"
              value={roi ? `${roi.benchmark.avg_roi.toFixed(0)}%` : '-'}
              color="yellow"
            />
            <KPIMiniCard
              label="Your Percentile"
              value={roi ? `${roi.benchmark.percentile}th` : '-'}
              color={
                roi && roi.benchmark.percentile >= 75
                  ? 'green'
                  : roi && roi.benchmark.percentile >= 50
                    ? 'yellow'
                    : 'red'
              }
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export default ROIMetrics;
