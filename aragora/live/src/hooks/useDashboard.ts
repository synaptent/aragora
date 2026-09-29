'use client';

import { useSWRFetch, type UseSWRFetchOptions } from './useSWRFetch';

// ============================================================================
// Types
// ============================================================================

/** Dashboard overview data */
export interface DashboardOverview {
  inbox: {
    total_unread: number;
    high_priority: number;
    needs_response: number;
    snoozed: number;
    assigned_to_me: number;
  };
  today: {
    emails_received: number;
    emails_sent: number;
    emails_archived: number;
    meetings_scheduled: number;
    action_items_completed: number;
    action_items_created: number;
  };
  team: {
    active_members: number;
    open_tickets: number;
    avg_response_time_mins: number;
    resolved_today: number;
  };
  ai: {
    emails_categorized: number;
    auto_responses_suggested: number;
    priority_predictions: number;
    debates_run: number;
  };
  cards: Array<{
    id: string;
    title: string;
    value: string;
    change: string;
    change_type: 'increase' | 'decrease' | 'neutral';
    icon: string;
  }>;
  generated_at: string;
}

/** Dashboard statistics */
export interface DashboardStats {
  period: string;
  email_volume: { labels: string[]; received: number[]; sent: number[]; archived: number[] };
  response_time: { labels: string[]; values: number[] };
  priority_distribution: { labels: string[]; values: number[] };
  categories: { labels: string[]; values: number[] };
  summary: {
    total_emails: number;
    avg_daily_emails: number;
    response_rate: number;
    avg_response_time_mins: number;
    ai_accuracy: number;
  };
}

/** Outcome dashboard quality score */
export interface OutcomeQuality {
  quality_score: number;
  consensus_rate: number;
  avg_rounds: number;
  total_decisions: number;
  completed_decisions: number;
  completion_rate: number;
  quality_change: number | null;
  trend: Array<Record<string, unknown>>;
  period: string;
}

/** Outcome dashboard agent entry */
export interface OutcomeAgent {
  rank: number;
  agent_id: string;
  agent_name: string;
  provider: string;
  model: string;
  elo: number;
  elo_change: number;
  debates: number;
  win_rate: number;
  brier_score: number | null;
  calibration_accuracy: number | null;
}

/** Usage summary */
export interface UsageSummary {
  debates_run: number;
  total_cost_usd: number;
  consensus_rate: number;
  avg_rounds: number;
  period: string;
}

/** Spend analytics summary */
export interface SpendSummary {
  total_spend_usd: string;
  total_api_calls: number;
  total_tokens: number;
  budget_limit_usd: number;
  budget_spent_usd: number;
  utilization_pct: number;
  trend_direction: 'increasing' | 'stable' | 'decreasing';
  avg_cost_per_decision: number;
}

type DashboardPeriod = 'day' | 'week' | 'month';
type OutcomePeriod = '7d' | '14d' | '30d' | '60d' | '90d';

// ============================================================================
// Core Dashboard Hooks
// ============================================================================

/**
 * Fetch dashboard overview.
 * Hits GET /api/v1/dashboard
 */
export function useDashboardOverview(
  refresh: boolean = false,
  options?: UseSWRFetchOptions<{ data: DashboardOverview }>,
) {
  const qs = refresh ? '?refresh=true' : '';
  const result = useSWRFetch<{ data: DashboardOverview }>(`/api/v1/dashboard${qs}`, {
    refreshInterval: 30000,
    ...options,
  });
  return { ...result, overview: result.data?.data ?? null };
}

/**
 * Fetch dashboard statistics.
 * Hits GET /api/v1/dashboard/stats
 */
export function useDashboardStats(
  period: DashboardPeriod = 'week',
  options?: UseSWRFetchOptions<{ data: DashboardStats }>,
) {
  const result = useSWRFetch<{ data: DashboardStats }>(`/api/v1/dashboard/stats?period=${period}`, {
    refreshInterval: 60000,
    ...options,
  });
  return { ...result, stats: result.data?.data ?? null };
}

/**
 * Fetch dashboard activity feed.
 * Hits GET /api/v1/dashboard/activity
 */
export function useDashboardActivity(
  limit: number = 20,
  options?: UseSWRFetchOptions<{
    data: { activities: Array<Record<string, unknown>>; total: number };
  }>,
) {
  const result = useSWRFetch<{
    data: { activities: Array<Record<string, unknown>>; total: number };
  }>(`/api/v1/dashboard/activity?limit=${limit}`, { refreshInterval: 30000, ...options });
  return { ...result, activities: result.data?.data?.activities ?? [] };
}

/**
 * Fetch inbox summary.
 * Hits GET /api/v1/dashboard/inbox-summary
 */
export function useDashboardInboxSummary(
  options?: UseSWRFetchOptions<{ data: Record<string, unknown> }>,
) {
  const result = useSWRFetch<{ data: Record<string, unknown> }>('/api/v1/dashboard/inbox-summary', {
    refreshInterval: 30000,
    ...options,
  });
  return { ...result, inbox: result.data?.data ?? null };
}

/**
 * Fetch dashboard stat cards.
 * Hits GET /api/v1/dashboard/stat-cards
 */
export function useDashboardStatCards(
  options?: UseSWRFetchOptions<{ data: { cards: Array<Record<string, unknown>> } }>,
) {
  const result = useSWRFetch<{ data: { cards: Array<Record<string, unknown>> } }>(
    '/api/v1/dashboard/stat-cards',
    { refreshInterval: 30000, ...options },
  );
  return { ...result, cards: result.data?.data?.cards ?? [] };
}

/**
 * Fetch quick actions.
 * Hits GET /api/v1/dashboard/quick-actions
 */
export function useDashboardQuickActions(
  options?: UseSWRFetchOptions<{ data: { actions: Array<Record<string, unknown>> } }>,
) {
  const result = useSWRFetch<{ data: { actions: Array<Record<string, unknown>> } }>(
    '/api/v1/dashboard/quick-actions',
    { refreshInterval: 60000, ...options },
  );
  return { ...result, actions: result.data?.data?.actions ?? [] };
}

/**
 * Fetch team performance metrics.
 * Hits GET /api/v1/dashboard/team-performance
 */
export function useDashboardTeamPerformance(
  options?: UseSWRFetchOptions<{ data: { teams: Array<Record<string, unknown>> } }>,
) {
  const result = useSWRFetch<{ data: { teams: Array<Record<string, unknown>> } }>(
    '/api/v1/dashboard/team-performance',
    { refreshInterval: 60000, ...options },
  );
  return { ...result, teams: result.data?.data?.teams ?? [] };
}

/**
 * Fetch urgent items.
 * Hits GET /api/v1/dashboard/urgent
 */
export function useDashboardUrgentItems(
  options?: UseSWRFetchOptions<{ data: { items: Array<Record<string, unknown>>; total: number } }>,
) {
  const result = useSWRFetch<{ data: { items: Array<Record<string, unknown>>; total: number } }>(
    '/api/v1/dashboard/urgent',
    { refreshInterval: 30000, ...options },
  );
  return { ...result, items: result.data?.data?.items ?? [] };
}

/**
 * Fetch pending actions.
 * Hits GET /api/v1/dashboard/pending-actions
 */
export function useDashboardPendingActions(
  options?: UseSWRFetchOptions<{
    data: { actions: Array<Record<string, unknown>>; total: number };
  }>,
) {
  const result = useSWRFetch<{ data: { actions: Array<Record<string, unknown>>; total: number } }>(
    '/api/v1/dashboard/pending-actions',
    { refreshInterval: 30000, ...options },
  );
  return { ...result, pendingActions: result.data?.data?.actions ?? [] };
}

/**
 * Fetch dashboard labels.
 * Hits GET /api/v1/dashboard/labels
 */
export function useDashboardLabels(
  options?: UseSWRFetchOptions<{ data: { labels: Array<Record<string, unknown>> } }>,
) {
  const result = useSWRFetch<{ data: { labels: Array<Record<string, unknown>> } }>(
    '/api/v1/dashboard/labels',
    { refreshInterval: 120000, ...options },
  );
  return { ...result, labels: result.data?.data?.labels ?? [] };
}

// ============================================================================
// Outcome Dashboard Hooks
// ============================================================================

/**
 * Fetch full outcome dashboard data.
 * Hits GET /api/v1/outcome-dashboard
 */
export function useOutcomeDashboard(
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: Record<string, unknown> }>,
) {
  const result = useSWRFetch<{ data: Record<string, unknown> }>(
    `/api/v1/outcome-dashboard?period=${period}`,
    { refreshInterval: 60000, ...options },
  );
  return { ...result, outcome: result.data?.data ?? null };
}

/**
 * Fetch decision quality score and trend.
 * Hits GET /api/v1/outcome-dashboard/quality
 */
export function useOutcomeQuality(
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: OutcomeQuality }>,
) {
  const result = useSWRFetch<{ data: OutcomeQuality }>(
    `/api/v1/outcome-dashboard/quality?period=${period}`,
    { refreshInterval: 60000, ...options },
  );
  return { ...result, quality: result.data?.data ?? null };
}

/**
 * Fetch agent leaderboard with ELO and calibration.
 * Hits GET /api/v1/outcome-dashboard/agents
 */
export function useOutcomeAgents(
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: { agents: OutcomeAgent[] } }>,
) {
  const result = useSWRFetch<{ data: { agents: OutcomeAgent[] } }>(
    `/api/v1/outcome-dashboard/agents?period=${period}`,
    { refreshInterval: 60000, ...options },
  );
  return { ...result, agents: result.data?.data?.agents ?? [] };
}

/**
 * Fetch decision history with quality scores.
 * Hits GET /api/v1/outcome-dashboard/history
 */
export function useOutcomeHistory(
  period: OutcomePeriod = '30d',
  limit: number = 50,
  options?: UseSWRFetchOptions<{
    data: { decisions: Array<Record<string, unknown>>; total: number };
  }>,
) {
  const result = useSWRFetch<{
    data: { decisions: Array<Record<string, unknown>>; total: number };
  }>(`/api/v1/outcome-dashboard/history?period=${period}&limit=${limit}`, {
    refreshInterval: 60000,
    ...options,
  });
  return {
    ...result,
    decisions: result.data?.data?.decisions ?? [],
    total: result.data?.data?.total ?? 0,
  };
}

/**
 * Fetch calibration curve data.
 * Hits GET /api/v1/outcome-dashboard/calibration
 */
export function useOutcomeCalibration(
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: { points: Array<Record<string, unknown>> } }>,
) {
  const result = useSWRFetch<{ data: { points: Array<Record<string, unknown>> } }>(
    `/api/v1/outcome-dashboard/calibration?period=${period}`,
    { refreshInterval: 120000, ...options },
  );
  return { ...result, points: result.data?.data?.points ?? [] };
}

// ============================================================================
// Usage Dashboard Hooks
// ============================================================================

/**
 * Fetch usage summary.
 * Hits GET /api/v1/usage/summary
 */
export function useUsageSummary(
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: UsageSummary }>,
) {
  const result = useSWRFetch<{ data: UsageSummary }>(`/api/v1/usage/summary?period=${period}`, {
    refreshInterval: 60000,
    ...options,
  });
  return { ...result, usage: result.data?.data ?? null };
}

/**
 * Fetch usage breakdown by dimension.
 * Hits GET /api/v1/usage/breakdown
 */
export function useUsageBreakdown(
  dimension: string = 'agent',
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: Record<string, unknown> }>,
) {
  const result = useSWRFetch<{ data: Record<string, unknown> }>(
    `/api/v1/usage/breakdown?dimension=${dimension}&period=${period}`,
    { refreshInterval: 60000, ...options },
  );
  return { ...result, breakdown: result.data?.data ?? null };
}

/**
 * Fetch budget status.
 * Hits GET /api/v1/usage/budget-status
 */
export function useBudgetStatusDashboard(
  options?: UseSWRFetchOptions<{ data: Record<string, unknown> }>,
) {
  const result = useSWRFetch<{ data: Record<string, unknown> }>('/api/v1/usage/budget-status', {
    refreshInterval: 60000,
    ...options,
  });
  return { ...result, budget: result.data?.data ?? null };
}

// ============================================================================
// Spend Analytics Dashboard Hooks
// ============================================================================

/**
 * Fetch spend analytics summary.
 * Hits GET /api/v1/analytics/spend/summary
 */
export function useSpendSummary(options?: UseSWRFetchOptions<{ data: SpendSummary }>) {
  const result = useSWRFetch<{ data: SpendSummary }>('/api/v1/analytics/spend/summary', {
    refreshInterval: 60000,
    ...options,
  });
  return { ...result, spend: result.data?.data ?? null };
}

/**
 * Fetch spend by agent breakdown.
 * Hits GET /api/v1/analytics/spend/by-agent
 */
export function useSpendByAgent(options?: UseSWRFetchOptions<{ data: Record<string, unknown> }>) {
  const result = useSWRFetch<{ data: Record<string, unknown> }>(
    '/api/v1/analytics/spend/by-agent',
    { refreshInterval: 60000, ...options },
  );
  return { ...result, agentSpend: result.data?.data ?? null };
}

/**
 * Fetch spend by decision breakdown.
 * Hits GET /api/v1/analytics/spend/by-decision
 */
export function useSpendByDecision(
  options?: UseSWRFetchOptions<{ data: Record<string, unknown> }>,
) {
  const result = useSWRFetch<{ data: Record<string, unknown> }>(
    '/api/v1/analytics/spend/by-decision',
    { refreshInterval: 60000, ...options },
  );
  return { ...result, decisionSpend: result.data?.data ?? null };
}

/**
 * Fetch spend budget limits and forecast.
 * Hits GET /api/v1/analytics/spend/budget
 */
export function useSpendBudgetForecast(
  options?: UseSWRFetchOptions<{ data: Record<string, unknown> }>,
) {
  const result = useSWRFetch<{ data: Record<string, unknown> }>('/api/v1/analytics/spend/budget', {
    refreshInterval: 120000,
    ...options,
  });
  return { ...result, budgetForecast: result.data?.data ?? null };
}
