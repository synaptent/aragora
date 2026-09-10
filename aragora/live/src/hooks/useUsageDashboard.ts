'use client';

import { useMemo } from 'react';
import { useSWRFetch, type UseSWRFetchOptions } from './useSWRFetch';

// ============================================================================
// Types - Usage Summary
// ============================================================================

export interface UsageSummary {
  debates: {
    total: number;
    completed: number;
    today: number;
    this_week: number;
    this_month: number;
  };
  tokens: { total_in: number; total_out: number; today: number; this_week: number };
  costs: { total_usd: number; today_usd: number; this_week_usd: number; this_month_usd: number };
  consensus: { rate: number; avg_confidence: number; avg_time_seconds: number };
  active_agents: number;
  period_start: string;
  period_end: string;
}

// ============================================================================
// Types - ROI Analysis
// ============================================================================

export interface ROIAnalysis {
  roi_percentage: number;
  time_saved_hours: number;
  cost_savings_usd: number;
  manual_equivalent_hours: number;
  cost_per_decision: number;
  value_generated_usd: number;
  benchmark: { industry: string; avg_roi: number; percentile: number };
  trends: {
    roi_trend: 'increasing' | 'stable' | 'decreasing';
    efficiency_trend: 'improving' | 'stable' | 'declining';
  };
}

// ============================================================================
// Types - Budget Status
// ============================================================================

export interface BudgetStatus {
  monthly_limit_usd: number;
  spent_usd: number;
  remaining_usd: number;
  utilization_percent: number;
  projected_end_of_month_usd: number;
  will_exceed: boolean;
  alert_level: 'normal' | 'warning' | 'critical';
  daily_average_usd: number;
  days_remaining: number;
}

// ============================================================================
// Types - Usage Forecast
// ============================================================================

export interface UsageForecast {
  projected_monthly_tokens: number;
  projected_monthly_cost_usd: number;
  projected_monthly_debates: number;
  growth_rate_percent: number;
  trend: 'increasing' | 'stable' | 'decreasing';
  confidence: number;
  recommendations: string[];
}

// ============================================================================
// Types - Industry Benchmarks
// ============================================================================

export interface IndustryBenchmark {
  industry: string;
  avg_consensus_rate: number;
  avg_decision_time_seconds: number;
  avg_cost_per_decision: number;
  avg_roi_percentage: number;
}

export type TimeRange = '24h' | '7d' | '30d' | '90d';

// ============================================================================
// Types - Cost Breakdown (used by CostBreakdown component)
// ============================================================================

export interface CostBreakdownItem {
  name: string;
  cost_usd: number;
  percentage: number;
  tokens: number;
  requests: number;
}

export interface CostBreakdown {
  total_cost_usd: number;
  by_agent: CostBreakdownItem[];
  by_model: CostBreakdownItem[];
}

// ============================================================================
// Types - Usage Trend
// ============================================================================

export interface UsageTrendPoint {
  date: string;
  debates: number;
  tokens: number;
  cost_usd: number;
  consensus_rate: number;
}

// ============================================================================
// Individual Hooks
// ============================================================================

/**
 * Hook for fetching usage summary data
 */
export function useUsageSummary(
  timeRange: TimeRange = '30d',
  options?: UseSWRFetchOptions<{ data: UsageSummary }>,
) {
  const result = useSWRFetch<{ data: UsageSummary }>(`/api/v1/usage/summary?range=${timeRange}`, {
    refreshInterval: 30000, // Refresh every 30 seconds
    ...options,
  });

  return { ...result, summary: result.data?.data ?? null };
}

/**
 * Hook for fetching ROI analysis
 */
export function useROIAnalysis(
  timeRange: TimeRange = '30d',
  options?: UseSWRFetchOptions<{ data: ROIAnalysis }>,
) {
  const result = useSWRFetch<{ data: ROIAnalysis }>(`/api/v1/usage/roi?range=${timeRange}`, {
    refreshInterval: 60000, // Refresh every minute
    ...options,
  });

  return { ...result, roi: result.data?.data ?? null };
}

/**
 * Hook for fetching budget status
 */
export function useBudgetStatus(options?: UseSWRFetchOptions<{ data: BudgetStatus }>) {
  const result = useSWRFetch<{ data: BudgetStatus }>('/api/v1/usage/budget-status', {
    refreshInterval: 30000, // Check budget frequently
    ...options,
  });

  return { ...result, budget: result.data?.data ?? null };
}

/**
 * Hook for fetching usage forecast
 */
export function useUsageForecast(options?: UseSWRFetchOptions<{ data: UsageForecast }>) {
  const result = useSWRFetch<{ data: UsageForecast }>('/api/v1/usage/forecast', {
    refreshInterval: 300000, // Refresh every 5 minutes
    ...options,
  });

  return { ...result, forecast: result.data?.data ?? null };
}

/**
 * Hook for fetching industry benchmarks
 */
export function useIndustryBenchmarks(
  options?: UseSWRFetchOptions<{ data: { benchmarks: IndustryBenchmark[] } }>,
) {
  const result = useSWRFetch<{ data: { benchmarks: IndustryBenchmark[] } }>(
    '/api/v1/usage/benchmarks',
    {
      refreshInterval: 3600000, // Refresh hourly (benchmarks don't change often)
      ...options,
    },
  );

  return { ...result, benchmarks: result.data?.data?.benchmarks ?? [] };
}

/**
 * Hook for fetching usage trend data over time
 */
export function useUsageTrend(
  timeRange: TimeRange = '30d',
  options?: UseSWRFetchOptions<{ data: { points: UsageTrendPoint[] } }>,
) {
  const result = useSWRFetch<{ data: { points: UsageTrendPoint[] } }>(
    `/api/v1/usage/trend?range=${timeRange}`,
    {
      refreshInterval: 60000, // Refresh every minute
      ...options,
    },
  );

  return { ...result, trend: result.data?.data?.points ?? [] };
}

/**
 * Hook for fetching cost breakdown by agent/model
 */
export function useCostBreakdown(
  timeRange: TimeRange = '30d',
  options?: UseSWRFetchOptions<{ data: CostBreakdown }>,
) {
  const result = useSWRFetch<{ data: CostBreakdown }>(
    `/api/v1/usage/cost-breakdown?range=${timeRange}`,
    {
      refreshInterval: 60000, // Refresh every minute
      ...options,
    },
  );

  return { ...result, breakdown: result.data?.data ?? null };
}

// ============================================================================
// Unified Dashboard Hook
// ============================================================================

/**
 * Unified hook for all usage dashboard data.
 * Combines usage summary, ROI, budget status, and forecast.
 *
 * @param timeRange  Time window for the summary / ROI data.
 * @param options.refreshInterval  Override the default SWR polling intervals
 *   (e.g. use a longer interval when WebSocket push is active).
 */
export function useUsageDashboard(
  timeRange: TimeRange = '30d',
  options?: { refreshInterval?: number },
) {
  const ri = options?.refreshInterval;
  const {
    summary,
    isLoading: summaryLoading,
    error: summaryError,
  } = useUsageSummary(timeRange, ri != null ? { refreshInterval: ri } : undefined);
  const {
    roi,
    isLoading: roiLoading,
    error: roiError,
  } = useROIAnalysis(timeRange, ri != null ? { refreshInterval: Math.max(ri, 60_000) } : undefined);
  const {
    budget,
    isLoading: budgetLoading,
    error: budgetError,
  } = useBudgetStatus(ri != null ? { refreshInterval: ri } : undefined);
  const {
    forecast,
    isLoading: forecastLoading,
    error: forecastError,
  } = useUsageForecast(ri != null ? { refreshInterval: Math.max(ri, 120_000) } : undefined);

  const isLoading = summaryLoading || roiLoading || budgetLoading || forecastLoading;
  const error = summaryError || roiError || budgetError || forecastError;

  // Transform to dashboard-friendly format
  const dashboardData = useMemo(() => {
    if (!summary) return null;

    return {
      // Debate metrics
      debates: {
        today: summary.debates.today,
        week: summary.debates.this_week,
        month: summary.debates.this_month,
        total: summary.debates.total,
        completed: summary.debates.completed,
      },
      // Consensus metrics
      consensus: {
        rate: summary.consensus.rate,
        avgConfidence: summary.consensus.avg_confidence,
        avgTimeToDecision: summary.consensus.avg_time_seconds,
      },
      // Cost metrics
      costs: {
        todayTokens: summary.tokens.today,
        weekTokens: summary.tokens.this_week,
        estimatedCost: summary.costs.today_usd,
        totalCost: summary.costs.total_usd,
        monthlyCost: summary.costs.this_month_usd,
      },
      // Agent metrics
      agents: {
        active: summary.active_agents,
        total: 15, // Could come from separate endpoint
        topPerformer: 'Claude', // Could come from rankings
        avgUptime: 99, // Could come from health endpoint
      },
      // ROI metrics
      roi: roi
        ? {
            percentage: roi.roi_percentage,
            timeSavedHours: roi.time_saved_hours,
            costSavingsUsd: roi.cost_savings_usd,
            costPerDecision: roi.cost_per_decision,
            valueGenerated: roi.value_generated_usd,
            industryBenchmark: roi.benchmark.avg_roi,
            percentile: roi.benchmark.percentile,
            trend: roi.trends.roi_trend,
          }
        : null,
      // Budget status
      budget: budget
        ? {
            limit: budget.monthly_limit_usd,
            spent: budget.spent_usd,
            remaining: budget.remaining_usd,
            utilization: budget.utilization_percent,
            projectedTotal: budget.projected_end_of_month_usd,
            willExceed: budget.will_exceed,
            alertLevel: budget.alert_level,
            daysRemaining: budget.days_remaining,
          }
        : null,
      // Forecast
      forecast: forecast
        ? {
            monthlyTokens: forecast.projected_monthly_tokens,
            monthlyCost: forecast.projected_monthly_cost_usd,
            monthlyDebates: forecast.projected_monthly_debates,
            growthRate: forecast.growth_rate_percent,
            trend: forecast.trend,
            confidence: forecast.confidence,
          }
        : null,
      // Metadata
      lastUpdated: new Date().toISOString(),
    };
  }, [summary, roi, budget, forecast]);

  return {
    // Raw data
    summary,
    roi,
    budget,
    forecast,

    // Transformed dashboard data
    dashboardData,

    // State
    isLoading,
    error,
  };
}

// ============================================================================
// Export
// ============================================================================

export default useUsageDashboard;
