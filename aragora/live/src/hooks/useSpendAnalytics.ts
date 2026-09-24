'use client';

import { useSWRFetch, type UseSWRFetchOptions } from './useSWRFetch';

// ============================================================================
// Types — match the backend SpendAnalytics dataclasses
// ============================================================================

export interface SpendDataPoint {
  date: string;
  cost_usd: number;
}

export interface SpendTrend {
  workspace_id: string;
  period: string;
  points: SpendDataPoint[];
  total_usd: number;
  avg_daily_usd: number;
}

export interface SpendForecast {
  workspace_id: string;
  forecast_days: number;
  projected_total_usd: number;
  projected_daily_avg_usd: number;
  trend: 'increasing' | 'stable' | 'decreasing';
  confidence: number;
}

export interface SpendAnomaly {
  date: string;
  actual_usd: number;
  expected_usd: number;
  z_score: number;
  severity: 'warning' | 'critical';
  description: string;
}

/** Shape returned by GET /api/v1/spend/analytics */
export interface SpendAnalyticsData {
  trend: SpendTrend;
  by_provider: Record<string, number>;
  by_agent: Record<string, number>;
  forecast: SpendForecast;
  anomalies: SpendAnomaly[];
}

export type SpendPeriod = '7d' | '14d' | '30d' | '60d' | '90d';

// ============================================================================
// Types — Spend Analytics Dashboard (new /api/v1/analytics/spend/* endpoints)
// ============================================================================

/** Shape returned by GET /api/v1/analytics/spend/summary */
export interface SpendDashboardSummary {
  total_spend_usd: string;
  total_api_calls: number;
  total_tokens: number;
  budget_limit_usd: number;
  budget_spent_usd: number;
  utilization_pct: number;
  trend_direction: 'increasing' | 'stable' | 'decreasing';
  avg_cost_per_decision: number;
}

/** Shape returned by GET /api/v1/analytics/spend/trends */
export interface SpendDashboardTrends {
  org_id: string;
  period: string;
  days: number;
  data_points: Array<{ date: string; amount_usd: number; [key: string]: unknown }>;
}

/** Single agent cost entry from GET /api/v1/analytics/spend/by-agent */
export interface AgentSpendEntry {
  agent_name: string;
  cost_usd: string;
  percentage: number;
}

/** Shape returned by GET /api/v1/analytics/spend/by-agent */
export interface SpendDashboardByAgent {
  workspace_id: string;
  total_usd: string;
  agents: AgentSpendEntry[];
}

/** Single decision cost entry from GET /api/v1/analytics/spend/by-decision */
export interface DecisionSpendEntry {
  debate_id: string;
  cost_usd: string;
}

/** Shape returned by GET /api/v1/analytics/spend/by-decision */
export interface SpendDashboardByDecision {
  workspace_id: string;
  decisions: DecisionSpendEntry[];
  count: number;
}

/** Shape returned by GET /api/v1/analytics/spend/budget */
export interface SpendDashboardBudget {
  org_id: string;
  budgets: Array<Record<string, unknown>>;
  total_budget_usd: number;
  total_spent_usd: number;
  total_remaining_usd: number;
  utilization_pct: number;
  forecast_exhaustion_days: number | null;
}

// ============================================================================
// Hooks — Original /api/v1/spend/analytics endpoints
// ============================================================================

/**
 * Fetch the full spend analytics summary in a single request.
 * Hits GET /api/v1/spend/analytics?period=...&workspace_id=...
 */
export function useSpendAnalytics(
  period: SpendPeriod = '30d',
  workspaceId: string = 'default',
  options?: UseSWRFetchOptions<{ data: SpendAnalyticsData }>,
) {
  const result = useSWRFetch<{ data: SpendAnalyticsData }>(
    `/api/v1/spend/analytics?period=${period}&workspace_id=${workspaceId}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, analytics: result.data?.data ?? null };
}

/**
 * Fetch only the spend trend (daily timeline).
 */
export function useSpendTrend(
  period: SpendPeriod = '30d',
  workspaceId: string = 'default',
  options?: UseSWRFetchOptions<{ data: SpendTrend }>,
) {
  const result = useSWRFetch<{ data: SpendTrend }>(
    `/api/v1/spend/analytics/trend?period=${period}&workspace_id=${workspaceId}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, trend: result.data?.data ?? null };
}

/**
 * Fetch the cost forecast.
 */
export function useSpendForecast(
  workspaceId: string = 'default',
  days: number = 30,
  options?: UseSWRFetchOptions<{ data: SpendForecast }>,
) {
  const result = useSWRFetch<{ data: SpendForecast }>(
    `/api/v1/spend/analytics/forecast?workspace_id=${workspaceId}&days=${days}`,
    { refreshInterval: 300000, ...options },
  );

  return { ...result, forecast: result.data?.data ?? null };
}

/**
 * Fetch spend anomalies.
 */
export function useSpendAnomalies(
  period: SpendPeriod = '30d',
  workspaceId: string = 'default',
  options?: UseSWRFetchOptions<{ data: { anomalies: SpendAnomaly[] } }>,
) {
  const result = useSWRFetch<{ data: { anomalies: SpendAnomaly[] } }>(
    `/api/v1/spend/analytics/anomalies?period=${period}&workspace_id=${workspaceId}`,
    { refreshInterval: 300000, ...options },
  );

  return { ...result, anomalies: result.data?.data?.anomalies ?? [] };
}

// ============================================================================
// Hooks — New /api/v1/analytics/spend/* Dashboard endpoints
// ============================================================================

/**
 * Fetch spend dashboard summary.
 * Hits GET /api/v1/analytics/spend/summary?workspace_id=...&org_id=...
 */
export function useSpendDashboardSummary(
  workspaceId: string = 'default',
  orgId: string = 'default',
  options?: UseSWRFetchOptions<SpendDashboardSummary>,
) {
  const result = useSWRFetch<SpendDashboardSummary>(
    `/api/v1/analytics/spend/summary?workspace_id=${workspaceId}&org_id=${orgId}`,
    { refreshInterval: 30000, ...options },
  );

  return { ...result, summary: result.data ?? null };
}

/**
 * Fetch spend trends over time.
 * Hits GET /api/v1/analytics/spend/trends?org_id=...&period=...&days=...
 */
export function useSpendDashboardTrends(
  orgId: string = 'default',
  period: 'daily' | 'weekly' | 'monthly' = 'daily',
  days: number = 30,
  options?: UseSWRFetchOptions<SpendDashboardTrends>,
) {
  const result = useSWRFetch<SpendDashboardTrends>(
    `/api/v1/analytics/spend/trends?org_id=${orgId}&period=${period}&days=${days}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, trends: result.data ?? null };
}

/**
 * Fetch spend breakdown by agent.
 * Hits GET /api/v1/analytics/spend/by-agent?workspace_id=...
 */
export function useSpendDashboardByAgent(
  workspaceId: string = 'default',
  options?: UseSWRFetchOptions<SpendDashboardByAgent>,
) {
  const result = useSWRFetch<SpendDashboardByAgent>(
    `/api/v1/analytics/spend/by-agent?workspace_id=${workspaceId}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, agentBreakdown: result.data ?? null };
}

/**
 * Fetch spend breakdown by decision/debate.
 * Hits GET /api/v1/analytics/spend/by-decision?workspace_id=...&limit=...
 */
export function useSpendDashboardByDecision(
  workspaceId: string = 'default',
  limit: number = 20,
  options?: UseSWRFetchOptions<SpendDashboardByDecision>,
) {
  const result = useSWRFetch<SpendDashboardByDecision>(
    `/api/v1/analytics/spend/by-decision?workspace_id=${workspaceId}&limit=${limit}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, decisionBreakdown: result.data ?? null };
}

/**
 * Fetch budget status and forecast.
 * Hits GET /api/v1/analytics/spend/budget?org_id=...
 */
export function useSpendDashboardBudget(
  orgId: string = 'default',
  options?: UseSWRFetchOptions<SpendDashboardBudget>,
) {
  const result = useSWRFetch<SpendDashboardBudget>(
    `/api/v1/analytics/spend/budget?org_id=${orgId}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, budget: result.data ?? null };
}
