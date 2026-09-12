'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { UsageBreakdown } from '@/components/dashboard/UsageBreakdown';
import { BudgetStatus } from '@/components/dashboard/BudgetStatus';
import { ROIMetrics } from '@/components/dashboard/ROIMetrics';
import { CostBreakdown } from '@/components/dashboard/CostBreakdown';
import { UsageTrend } from '@/components/dashboard/UsageTrend';
import {
  useUsageSummary,
  useROIAnalysis,
  useBudgetStatus,
  useUsageForecast,
  useUsageTrend,
  useCostBreakdown,
  type TimeRange,
} from '@/hooks/useUsageDashboard';

export default function UsagePage() {
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');

  const { summary, isLoading: summaryLoading } = useUsageSummary(timeRange);
  const { roi, isLoading: roiLoading } = useROIAnalysis(timeRange);
  const { budget, isLoading: budgetLoading } = useBudgetStatus();
  const { forecast, isLoading: forecastLoading } = useUsageForecast();
  const { breakdown, isLoading: breakdownLoading } = useCostBreakdown(timeRange);
  const { trend, isLoading: trendLoading } = useUsageTrend(timeRange);

  const getTimeRangeLabel = (range: TimeRange): string => {
    switch (range) {
      case '24h':
        return 'Last 24 Hours';
      case '7d':
        return 'Last 7 Days';
      case '30d':
        return 'Last 30 Days';
      case '90d':
        return 'Last 90 Days';
      default:
        return range;
    }
  };

  return (
    <ProtectedRoute>
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />

        <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
          <div className="container mx-auto px-4 py-6">
            {/* Header */}
            <div className="mb-6">
              <div className="flex items-center justify-between flex-wrap gap-4">
                <div>
                  <div className="flex items-center gap-3 mb-2">
                    <Link
                      href="/dashboard"
                      className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
                    >
                      DASHBOARD
                    </Link>
                    <span className="text-xs font-theme-data text-[var(--text-muted)]">/</span>
                    <span className="text-xs font-theme-data text-[var(--acid-green)]">USAGE</span>
                  </div>
                  <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-1">
                    {'>'} USAGE ANALYTICS
                  </h1>
                  <p className="text-xs text-[var(--text-muted)] font-theme-data">
                    {getTimeRangeLabel(timeRange)} {/* Debates, costs, ROI, and budget tracking */}
                  </p>
                </div>

                {/* Time Range Selector */}
                <div className="flex items-center gap-2">
                  {(['24h', '7d', '30d', '90d'] as TimeRange[]).map((range) => (
                    <button
                      key={range}
                      onClick={() => setTimeRange(range)}
                      className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
                        timeRange === range
                          ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/50'
                          : 'bg-[var(--surface)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/30'
                      }`}
                    >
                      {range.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Usage Breakdown (KPIs + Debate/Cost/Consensus details + Forecast) */}
            <UsageBreakdown
              summary={summary}
              forecast={forecast}
              timeRange={timeRange}
              loading={summaryLoading || forecastLoading}
            />

            {/* Trend + Budget Row */}
            <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
              <UsageTrend data={trend} loading={trendLoading} />
              <BudgetStatus budget={budget} loading={budgetLoading} />
            </div>

            {/* Cost Breakdown + ROI Row */}
            <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
              <CostBreakdown breakdown={breakdown} loading={breakdownLoading} />
              <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
                <ROIMetrics roi={roi} loading={roiLoading} />
              </div>
            </div>

            {/* Navigation */}
            <div className="mt-8 flex items-center gap-2 pt-4 border-t border-[var(--border)]">
              <span className="text-xs font-theme-data text-[var(--text-muted)]">Navigate:</span>
              <Link
                href="/dashboard"
                className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
              >
                DASHBOARD
              </Link>
              <Link
                href="/arena"
                className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
              >
                NEW DEBATE
              </Link>
              <Link
                href="/billing"
                className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
              >
                BILLING
              </Link>
              <Link
                href="/settings"
                className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
              >
                SETTINGS
              </Link>
            </div>
          </div>
        </main>
      </>
    </ProtectedRoute>
  );
}
