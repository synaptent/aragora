'use client';

import { useSWRFetch, type UseSWRFetchOptions } from './useSWRFetch';

// ============================================================================
// Types
// ============================================================================

export interface EloHistoryPoint {
  timestamp: string;
  elo: number;
}

export interface AgentEloDetail {
  agent_id: string;
  agent_name: string;
  elo: number;
  elo_change: number;
  rank: number | null;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number;
  games_played: number;
  debates_count: number;
  domain_performance?: Record<string, { elo: number }>;
  calibration_score?: number;
  calibration_accuracy?: number;
  elo_history: EloHistoryPoint[];
  generated_at: string;
}

export interface AgentTrendData {
  [agentName: string]: Array<{ period: string; elo: number; timestamp: string }>;
}

export interface AgentTrendsResponse {
  data: { trends: AgentTrendData; agents: string[]; granularity: string; generated_at: string };
}

export interface DomainLeaderboardEntry {
  agent_name: string;
  elo: number;
  domain_elo: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number;
  games: number;
}

export interface RankingStatsResponse {
  data: {
    mean_elo: number;
    median_elo: number;
    total_agents: number;
    total_matches: number;
    rating_distribution: Record<string, number>;
    trending_up: string[];
    trending_down: string[];
  };
}

// ============================================================================
// Hooks
// ============================================================================

/**
 * Fetch ELO trend data for top agents.
 * Uses the analytics trends endpoint which returns per-agent
 * ELO history grouped by time period.
 */
export function useEloTrends(
  agents?: string,
  granularity: string = 'daily',
  options?: UseSWRFetchOptions<AgentTrendsResponse>,
) {
  const params = new URLSearchParams({ granularity });
  if (agents) params.set('agents', agents);

  const result = useSWRFetch<AgentTrendsResponse>(`/api/v1/analytics/agents/trends?${params}`, {
    refreshInterval: 60000,
    ...options,
  });

  return {
    ...result,
    trends: result.data?.data?.trends ?? null,
    agents: result.data?.data?.agents ?? [],
  };
}

/**
 * Fetch detailed ELO analytics for a single agent.
 * Includes ELO history for charting.
 */
export function useAgentEloDetail(
  agentId: string | null,
  options?: UseSWRFetchOptions<{ data: AgentEloDetail }>,
) {
  const result = useSWRFetch<{ data: AgentEloDetail }>(
    agentId ? `/api/v1/analytics/agents/${encodeURIComponent(agentId)}` : null,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, agent: result.data?.data ?? null };
}

/**
 * Fetch ranking stats (mean ELO, median, distribution, trending agents).
 */
export function useRankingStats(options?: UseSWRFetchOptions<RankingStatsResponse>) {
  const result = useSWRFetch<RankingStatsResponse>('/api/ranking/stats', {
    refreshInterval: 60000,
    ...options,
  });

  return { ...result, stats: result.data?.data ?? null };
}

/**
 * Fetch domain-specific leaderboard.
 * Falls back to the general leaderboard with domain filter.
 */
export function useDomainLeaderboard(
  domain: string | null,
  limit: number = 10,
  options?: UseSWRFetchOptions<{ data: { agents: DomainLeaderboardEntry[] } }>,
) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (domain) params.set('domain', domain);

  const result = useSWRFetch<{ data: { agents: DomainLeaderboardEntry[] } }>(
    `/api/leaderboard?${params}`,
    { refreshInterval: 60000, ...options },
  );

  return {
    ...result,
    agents:
      result.data?.data?.agents ??
      ((result.data as Record<string, unknown>)?.agents as DomainLeaderboardEntry[]) ??
      [],
  };
}
