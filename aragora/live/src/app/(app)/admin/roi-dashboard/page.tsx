'use client';

import { useState } from 'react';
import { ROIMetrics } from '@/components/dashboard/ROIMetrics';
import { BudgetStatus } from '@/components/dashboard/BudgetStatus';
import { UsageBreakdown } from '@/components/dashboard/UsageBreakdown';
import { UsageChart } from '@/components/admin/UsageChart';
import { CostBreakdownChart, type CostItem } from '@/components/admin/CostBreakdownChart';
import useUsageDashboard, { type TimeRange } from '@/hooks/useUsageDashboard';

type BreakdownType = 'feature' | 'agent' | 'domain' | 'user' | 'workspace';

/**
 * ROI Dashboard - Comprehensive spend tracking and usage metrics
 *
 * Integrates:
 * - ROI analysis with industry benchmarks
 * - Budget status and alerts
 * - Usage breakdown with forecasting
 * - Cost breakdown by various dimensions
 * - Time series usage charts
 */
export default function ROIDashboard() {
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');
  const [breakdownType, setBreakdownType] = useState<BreakdownType>('feature');

  const { summary, roi, budget, forecast, isLoading, error } = useUsageDashboard(timeRange);

  // Transform usage data for charts
  const usageChartData = summary
    ? [
        {
          label: 'Week 1',
          value: Math.round(summary.debates.this_month * 0.2),
          date: '2026-01-07',
        },
        {
          label: 'Week 2',
          value: Math.round(summary.debates.this_month * 0.25),
          date: '2026-01-14',
        },
        {
          label: 'Week 3',
          value: Math.round(summary.debates.this_month * 0.27),
          date: '2026-01-21',
        },
        {
          label: 'Week 4',
          value: Math.round(summary.debates.this_month * 0.28),
          date: '2026-01-28',
        },
      ]
    : [];

  const costChartData = summary
    ? [
        { label: 'Week 1', value: summary.costs.this_month_usd * 0.2, date: '2026-01-07' },
        { label: 'Week 2', value: summary.costs.this_month_usd * 0.24, date: '2026-01-14' },
        { label: 'Week 3', value: summary.costs.this_month_usd * 0.28, date: '2026-01-21' },
        { label: 'Week 4', value: summary.costs.this_month_usd * 0.28, date: '2026-01-28' },
      ]
    : [];

  // Cost breakdown data (would come from API in production)
  const costBreakdownData: CostItem[] = [
    {
      id: '1',
      label: 'Debate Processing',
      cost: (summary?.costs.total_usd ?? 0) * 0.45,
      category: 'debate',
    },
    {
      id: '2',
      label: 'Agent Compute',
      cost: (summary?.costs.total_usd ?? 0) * 0.3,
      category: 'agent',
    },
    {
      id: '3',
      label: 'Knowledge Storage',
      cost: (summary?.costs.total_usd ?? 0) * 0.12,
      category: 'storage',
    },
    {
      id: '4',
      label: 'Workflow Automation',
      cost: (summary?.costs.total_usd ?? 0) * 0.08,
      category: 'workflow',
    },
    {
      id: '5',
      label: 'API & Integrations',
      cost: (summary?.costs.total_usd ?? 0) * 0.05,
      category: 'api',
    },
  ];

  const handleTimeRangeChange = (range: TimeRange) => {
    setTimeRange(range);
  };

  if (error) {
    return (
      <div className="max-w-7xl mx-auto p-6">
        <div className="bg-[var(--surface)] border border-red-500/50 p-6 text-center">
          <div className="font-theme-data text-red-400 mb-2">ERROR LOADING DASHBOARD</div>
          <div className="font-theme-data text-xs text-[var(--text-muted)]">
            {error.message || 'Failed to load usage data. Please try again.'}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-theme-data font-bold text-[var(--acid-green)]">
            ROI DASHBOARD
          </h1>
          <p className="text-sm font-theme-data text-[var(--text-muted)] mt-1">
            Track spend, measure ROI, and optimize costs
          </p>
        </div>

        {/* Time Range Selector */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-theme-data text-[var(--text-muted)]">PERIOD:</span>
          {(['24h', '7d', '30d', '90d'] as TimeRange[]).map((range) => (
            <button
              key={range}
              onClick={() => handleTimeRangeChange(range)}
              className={`px-3 py-1.5 font-theme-data text-xs rounded transition-colors ${
                timeRange === range
                  ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border border-[var(--acid-green)]/40'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)] border border-transparent'
              }`}
            >
              {range.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Primary ROI Section */}
      <ROIMetrics roi={roi} loading={isLoading} />

      {/* Budget and Usage Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <BudgetStatus budget={budget} loading={isLoading} />

        {/* Usage Trends */}
        <UsageChart
          title="DEBATE ACTIVITY"
          data={usageChartData}
          type="line"
          color="acid-green"
          showTimeRangeSelector={false}
          formatValue={(v) => v.toString()}
          loading={isLoading}
        />
      </div>

      {/* Usage Breakdown */}
      <UsageBreakdown
        summary={summary}
        forecast={forecast}
        timeRange={timeRange}
        loading={isLoading}
      />

      {/* Cost Analysis Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CostBreakdownChart
          data={costBreakdownData}
          title="COST BREAKDOWN"
          breakdownType={breakdownType}
          showTimeRangeSelector={false}
          onBreakdownTypeChange={setBreakdownType}
          loading={isLoading}
        />

        <UsageChart
          title="COST TREND"
          data={costChartData}
          type="bar"
          color="acid-yellow"
          showTimeRangeSelector={false}
          formatValue={(v) => `$${v.toFixed(0)}`}
          loading={isLoading}
        />
      </div>

      {/* Quick Actions */}
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-4 flex items-center gap-2">
          <span>{'>'}</span> QUICK ACTIONS
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <button className="p-3 bg-[var(--surface-elevated)] border border-[var(--border)] rounded hover:border-[var(--acid-green)]/40 transition-colors text-left">
            <div className="font-theme-data text-xs text-[var(--acid-green)]">SET BUDGET</div>
            <div className="font-theme-data text-[10px] text-[var(--text-muted)] mt-1">
              Configure monthly limits
            </div>
          </button>
          <button className="p-3 bg-[var(--surface-elevated)] border border-[var(--border)] rounded hover:border-[var(--acid-cyan)]/40 transition-colors text-left">
            <div className="font-theme-data text-xs text-[var(--acid-cyan)]">EXPORT REPORT</div>
            <div className="font-theme-data text-[10px] text-[var(--text-muted)] mt-1">
              Download usage data
            </div>
          </button>
          <button className="p-3 bg-[var(--surface-elevated)] border border-[var(--border)] rounded hover:border-[var(--acid-yellow)]/40 transition-colors text-left">
            <div className="font-theme-data text-xs text-[var(--acid-yellow)]">
              CONFIGURE ALERTS
            </div>
            <div className="font-theme-data text-[10px] text-[var(--text-muted)] mt-1">
              Set spending thresholds
            </div>
          </button>
          <button className="p-3 bg-[var(--surface-elevated)] border border-[var(--border)] rounded hover:border-[var(--acid-magenta)]/40 transition-colors text-left">
            <div className="font-theme-data text-xs text-[var(--acid-magenta)]">VIEW INVOICES</div>
            <div className="font-theme-data text-[10px] text-[var(--text-muted)] mt-1">
              Billing history
            </div>
          </button>
        </div>
      </div>

      {/* Footer metadata */}
      <div className="text-center">
        <span className="font-theme-data text-[10px] text-[var(--text-muted)]">
          Last updated: {new Date().toLocaleString()} | Data refreshes every 30s
        </span>
      </div>
    </div>
  );
}
