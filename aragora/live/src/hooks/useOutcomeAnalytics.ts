'use client';

import { useSWRFetch, invalidateCache, type UseSWRFetchOptions } from './useSWRFetch';

// ============================================================================
// Types
// ============================================================================

export interface QualityTrendPoint {
  timestamp: string;
  consensus_rate: number;
  avg_confidence: number;
  avg_rounds: number;
  debate_count: number;
}

export interface QualityScore {
  quality_score: number;
  consensus_rate: number;
  avg_rounds: number;
  total_decisions: number;
  completed_decisions: number;
  completion_rate: number;
  quality_change: number | null;
  trend: QualityTrendPoint[];
  period: string;
}

export interface AgentLeaderboardEntry {
  rank: number;
  agent_id: string;
  agent_name: string;
  provider: string;
  model: string;
  elo: number;
  elo_change: number;
  debates: number;
  messages: number;
  win_rate: number;
  error_rate: number;
  avg_response_ms: number;
  consensus_contributions: number;
  brier_score: number | null;
  calibration_accuracy: number | null;
  calibration_count: number;
}

export interface AgentLeaderboardData {
  agents: AgentLeaderboardEntry[];
  count: number;
  period: string;
}

export interface DecisionHistoryEntry {
  debate_id: string;
  task: string;
  status: string;
  consensus_reached: boolean;
  quality_score: number;
  rounds: number;
  agents: string[];
  agent_count: number;
  duration_seconds: number;
  total_messages: number;
  total_votes: number;
  cost: string;
  created_at: string;
}

export interface DecisionHistoryData {
  decisions: DecisionHistoryEntry[];
  total: number;
  limit: number;
  offset: number;
  period: string;
}

export interface CalibrationPoint {
  bucket: string;
  predicted: number;
  actual: number;
  count: number;
}

export interface CalibrationBin {
  predicted_confidence: number;
  actual_accuracy: number;
  count: number;
}

export interface CalibrationData {
  points: CalibrationPoint[];
  bins?: CalibrationBin[];
  ece?: number;
  total_observations: number;
  period: string;
}

export interface OutcomeDashboardData {
  quality: QualityScore;
  agents: AgentLeaderboardData;
  history: DecisionHistoryData;
  calibration: CalibrationData;
  period: string;
}

export type OutcomePeriod = '24h' | '7d' | '30d' | '90d' | '365d';

// ============================================================================
// Individual Hooks
// ============================================================================

/**
 * Hook for fetching the full outcome dashboard data in a single request.
 */
export function useOutcomeDashboard(
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: OutcomeDashboardData }>,
) {
  const result = useSWRFetch<{ data: OutcomeDashboardData }>(
    `/api/v1/outcome-dashboard?period=${period}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, dashboard: result.data?.data ?? null };
}

/**
 * Hook for fetching just the quality score and trend.
 */
export function useQualityScore(
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: QualityScore }>,
) {
  const result = useSWRFetch<{ data: QualityScore }>(
    `/api/v1/outcome-dashboard/quality?period=${period}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, quality: result.data?.data ?? null };
}

/**
 * Hook for fetching the agent leaderboard with ELO and calibration.
 */
export function useOutcomeAgents(
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: AgentLeaderboardData }>,
) {
  const result = useSWRFetch<{ data: AgentLeaderboardData }>(
    `/api/v1/outcome-dashboard/agents?period=${period}`,
    { refreshInterval: 120000, ...options },
  );

  return { ...result, leaderboard: result.data?.data ?? null };
}

/**
 * Hook for fetching paginated decision history.
 */
export function useDecisionHistory(
  period: OutcomePeriod = '30d',
  limit: number = 50,
  offset: number = 0,
  options?: UseSWRFetchOptions<{ data: DecisionHistoryData }>,
) {
  const result = useSWRFetch<{ data: DecisionHistoryData }>(
    `/api/v1/outcome-dashboard/history?period=${period}&limit=${limit}&offset=${offset}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, history: result.data?.data ?? null };
}

/**
 * Hook for fetching calibration curve data.
 */
export function useCalibrationCurve(
  period: OutcomePeriod = '30d',
  options?: UseSWRFetchOptions<{ data: CalibrationData }>,
) {
  const result = useSWRFetch<{ data: CalibrationData }>(
    `/api/v1/outcome-dashboard/calibration?period=${period}`,
    { refreshInterval: 300000, ...options },
  );

  return { ...result, calibration: result.data?.data ?? null };
}

// ============================================================================
// Unified Hook
// ============================================================================

/**
 * Unified hook that fetches the full outcome dashboard in one request.
 * Preferred over individual hooks for the main dashboard page.
 */
export function useOutcomeAnalytics(period: OutcomePeriod = '30d') {
  const { dashboard, isLoading, error, mutate } = useOutcomeDashboard(period);

  const refresh = () => {
    invalidateCache('/api/v1/outcome-dashboard');
    invalidateCache('/api/v1/outcome-dashboard/quality');
    invalidateCache('/api/v1/outcome-dashboard/agents');
    invalidateCache('/api/v1/outcome-dashboard/history');
    invalidateCache('/api/v1/outcome-dashboard/calibration');
    mutate();
  };

  return {
    // Data (unpacked from dashboard for convenience)
    quality: dashboard?.quality ?? null,
    agents: dashboard?.agents ?? null,
    history: dashboard?.history ?? null,
    calibration: dashboard?.calibration ?? null,

    // Raw
    dashboard,

    // State
    isLoading,
    error,

    // Actions
    refresh,
  };
}

export default useOutcomeAnalytics;
