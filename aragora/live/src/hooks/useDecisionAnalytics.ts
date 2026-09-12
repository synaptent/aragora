'use client';

import { useSWRFetch, invalidateCache, type UseSWRFetchOptions } from './useSWRFetch';

// ============================================================================
// Types
// ============================================================================

export interface DecisionOverview {
  total_decisions: number;
  consensus_reached: number;
  consensus_rate: number;
  avg_confidence: number;
  avg_rounds: number;
  period: string;
}

export interface QualityTrendPoint {
  timestamp: string;
  consensus_rate: number;
  avg_confidence: number;
  avg_rounds: number;
  debate_count: number;
}

export interface QualityTrend {
  period: string;
  points: QualityTrendPoint[];
  count: number;
}

export interface DecisionOutcome {
  debate_id: string;
  task: string;
  consensus_reached: boolean;
  confidence: number;
  rounds: number;
  agents: string[];
  duration_seconds: number;
  created_at: string;
}

export interface OutcomesList {
  outcomes: DecisionOutcome[];
  total: number;
  limit: number;
  offset: number;
  period: string;
}

export interface AgentQualityMetric {
  agent_id: string;
  agent_name: string;
  debates_participated: number;
  consensus_contributions: number;
  avg_confidence: number;
  contribution_score: number;
}

export interface AgentQualityData {
  agents: AgentQualityMetric[];
  count: number;
  period: string;
}

export interface DomainMetric {
  domain: string;
  decision_count: number;
  percentage: number;
}

export interface DomainData {
  domains: DomainMetric[];
  total_decisions: number;
  count: number;
  period: string;
}

export type AnalyticsPeriod = '24h' | '7d' | '30d' | '90d' | '365d';

// ============================================================================
// Individual Hooks
// ============================================================================

/**
 * Hook for fetching decision analytics overview (totals, rates, averages).
 */
export function useDecisionOverview(
  period: AnalyticsPeriod = '30d',
  options?: UseSWRFetchOptions<{ data: DecisionOverview }>,
) {
  const result = useSWRFetch<{ data: DecisionOverview }>(
    `/api/v1/decision-analytics/overview?period=${period}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, overview: result.data?.data ?? null };
}

/**
 * Hook for fetching decision quality trends over time.
 */
export function useDecisionTrends(
  period: AnalyticsPeriod = '90d',
  options?: UseSWRFetchOptions<{ data: QualityTrend }>,
) {
  const result = useSWRFetch<{ data: QualityTrend }>(
    `/api/v1/decision-analytics/trends?period=${period}`,
    {
      refreshInterval: 120000, // Refresh every 2 minutes
      ...options,
    },
  );

  return { ...result, trends: result.data?.data ?? null };
}

/**
 * Hook for fetching paginated decision outcomes list.
 */
export function useDecisionOutcomes(
  period: AnalyticsPeriod = '30d',
  limit: number = 50,
  offset: number = 0,
  options?: UseSWRFetchOptions<{ data: OutcomesList }>,
) {
  const result = useSWRFetch<{ data: OutcomesList }>(
    `/api/v1/decision-analytics/outcomes?period=${period}&limit=${limit}&offset=${offset}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, outcomes: result.data?.data ?? null };
}

/**
 * Hook for fetching per-agent quality metrics.
 */
export function useAgentQuality(
  period: AnalyticsPeriod = '30d',
  options?: UseSWRFetchOptions<{ data: AgentQualityData }>,
) {
  const result = useSWRFetch<{ data: AgentQualityData }>(
    `/api/v1/decision-analytics/agents?period=${period}`,
    { refreshInterval: 120000, ...options },
  );

  return { ...result, agentMetrics: result.data?.data ?? null };
}

/**
 * Hook for fetching quality by domain/topic.
 */
export function useDomainQuality(
  period: AnalyticsPeriod = '30d',
  options?: UseSWRFetchOptions<{ data: DomainData }>,
) {
  const result = useSWRFetch<{ data: DomainData }>(
    `/api/v1/decision-analytics/domains?period=${period}`,
    { refreshInterval: 120000, ...options },
  );

  return { ...result, domainMetrics: result.data?.data ?? null };
}

// ============================================================================
// Unified Hook
// ============================================================================

/**
 * Unified hook for all decision analytics data with combined loading/error state.
 */
export function useDecisionAnalytics(period: AnalyticsPeriod = '30d') {
  const {
    overview,
    isLoading: overviewLoading,
    error: overviewError,
  } = useDecisionOverview(period);

  const { trends, isLoading: trendsLoading, error: trendsError } = useDecisionTrends(period);

  const {
    outcomes,
    isLoading: outcomesLoading,
    error: outcomesError,
  } = useDecisionOutcomes(period);

  const { agentMetrics, isLoading: agentsLoading, error: agentsError } = useAgentQuality(period);

  const {
    domainMetrics,
    isLoading: domainsLoading,
    error: domainsError,
  } = useDomainQuality(period);

  const isLoading =
    overviewLoading || trendsLoading || outcomesLoading || agentsLoading || domainsLoading;
  const error = overviewError || trendsError || outcomesError || agentsError || domainsError;

  const refresh = () => {
    invalidateCache('/api/v1/decision-analytics/overview');
    invalidateCache('/api/v1/decision-analytics/trends');
    invalidateCache('/api/v1/decision-analytics/outcomes');
    invalidateCache('/api/v1/decision-analytics/agents');
    invalidateCache('/api/v1/decision-analytics/domains');
  };

  return {
    // Data
    overview,
    trends,
    outcomes,
    agentMetrics,
    domainMetrics,

    // State
    isLoading,
    error,

    // Actions
    refresh,
  };
}

export default useDecisionAnalytics;
