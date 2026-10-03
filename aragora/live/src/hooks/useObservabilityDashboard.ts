'use client';

import { useSWRFetch, type UseSWRFetchOptions } from './useSWRFetch';

export interface ObservabilityAgentRanking {
  name: string;
  rating: number;
  matches: number;
  win_rate: number;
}

export interface ObservabilityCircuitBreaker {
  name: string;
  state: string;
  failure_count: number;
  success_count?: number;
}

export interface ObservabilityRecentRun {
  id: string;
  goal: string;
  status: string;
  started_at: string;
}

export interface ObservabilityOracleStream {
  sessions_started: number;
  sessions_completed: number;
  sessions_cancelled: number;
  sessions_errors: number;
  active_sessions: number;
  stalls_waiting_first_token: number;
  stalls_stream_inactive: number;
  stalls_total: number;
  ttft_samples: number;
  ttft_avg_ms: number | null;
  ttft_last_ms: number | null;
  available: boolean;
}

export interface ObservabilitySettlementReview {
  running: boolean;
  interval_hours: number | null;
  max_receipts_per_run: number | null;
  startup_delay_seconds: number | null;
  stats: {
    total_runs: number;
    total_receipts_scanned: number;
    total_receipts_updated: number;
    total_calibration_predictions: number;
    failures: number;
    success_rate: number;
    last_run: string | null;
    last_result: {
      receipts_scanned: number;
      receipts_due: number;
      receipts_updated: number;
      calibration_predictions_recorded: number;
      unresolved_due: number;
      started_at: string;
      completed_at: string;
      duration_seconds: number;
      success: boolean;
      error: string | null;
    } | null;
  } | null;
  available: boolean;
}

export interface ObservabilityDashboardData {
  timestamp: number;
  collection_time_ms: number;
  debate_metrics: {
    total_debates: number;
    avg_duration_seconds: number;
    consensus_rate: number;
    available: boolean;
  };
  agent_rankings: {
    top_agents: ObservabilityAgentRanking[];
    available: boolean;
  };
  circuit_breakers: {
    breakers: ObservabilityCircuitBreaker[];
    available: boolean;
  };
  self_improve: {
    total_cycles: number;
    successful: number;
    failed: number;
    recent_runs: ObservabilityRecentRun[];
    available: boolean;
  };
  oracle_stream: ObservabilityOracleStream;
  settlement_review: ObservabilitySettlementReview;
  system_health: {
    memory_percent: number | null;
    cpu_percent: number | null;
    pid: number;
    available: boolean;
  };
  error_rates: {
    total_requests: number;
    total_errors: number;
    error_rate: number;
    available: boolean;
  };
}

/**
 * Shared observability dashboard hook for operational telemetry surfaces.
 */
export function useObservabilityDashboard(
  options?: UseSWRFetchOptions<ObservabilityDashboardData>
) {
  const result = useSWRFetch<ObservabilityDashboardData>(
    '/api/v1/observability/dashboard',
    {
      refreshInterval: 10000,
      ...options,
    }
  );

  return {
    ...result,
    dashboard: result.data ?? null,
  };
}

/**
 * Compact settlement/oracle telemetry hook for non-admin surfaces.
 */
export function useSettlementOracleTelemetry(
  options?: UseSWRFetchOptions<ObservabilityDashboardData>
) {
  const { dashboard, ...rest } = useObservabilityDashboard({
    refreshInterval: 30000,
    ...options,
  });

  return {
    ...rest,
    settlementReview: dashboard?.settlement_review ?? null,
    oracleStream: dashboard?.oracle_stream ?? null,
  };
}
