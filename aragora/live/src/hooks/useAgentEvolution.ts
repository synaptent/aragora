'use client';

import { useCallback } from 'react';
import { useSWRFetch, invalidateCache, type UseSWRFetchOptions } from './useSWRFetch';
import { useApi } from './useApi';

// ============================================================================
// Types
// ============================================================================

export interface EvolutionEvent {
  id: string;
  agent_name: string;
  event_type:
    'persona_change' | 'prompt_modification' | 'elo_adjustment' | 'nomic_proposal' | 'rollback';
  timestamp: string;
  description: string;
  old_value: string | null;
  new_value: string | null;
  elo_before: number | null;
  elo_after: number | null;
  nomic_cycle_id: string | null;
  approved: boolean | null;
  approved_by: string | null;
}

export interface EvolutionTimeline {
  events: EvolutionEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface EloTrendPoint {
  timestamp: string;
  elo: number;
  debate_id: string | null;
  change: number;
}

export interface AgentEloTrend {
  agent_name: string;
  provider: string;
  current_elo: number;
  trend: EloTrendPoint[];
  peak_elo: number;
  lowest_elo: number;
  total_debates: number;
}

export interface EloTrendsData {
  agents: AgentEloTrend[];
  period: string;
}

export interface PendingChange {
  id: string;
  agent_name: string;
  change_type: 'persona_update' | 'prompt_rewrite' | 'parameter_tune' | 'model_swap';
  nomic_cycle_id: string;
  proposed_at: string;
  proposed_by: string;
  description: string;
  diff_summary: string;
  old_content: string;
  new_content: string;
  impact_estimate: string;
  status: 'pending' | 'approved' | 'rejected';
}

export interface PendingChangesData {
  changes: PendingChange[];
  total_pending: number;
}

// ============================================================================
// Mock/Fallback Data
// ============================================================================

const now = Date.now();

const MOCK_TIMELINE: EvolutionTimeline = {
  events: [
    {
      id: 'evt-001',
      agent_name: 'claude-3-opus',
      event_type: 'persona_change',
      timestamp: new Date(now - 2 * 60 * 60 * 1000).toISOString(),
      description:
        'Persona shifted from "cautious analyst" to "balanced synthesizer" after 15 debate cycles',
      old_value: 'cautious_analyst',
      new_value: 'balanced_synthesizer',
      elo_before: 1420,
      elo_after: 1435,
      nomic_cycle_id: 'nomic-042',
      approved: true,
      approved_by: 'admin@acme.com',
    },
    {
      id: 'evt-002',
      agent_name: 'gpt-4-turbo',
      event_type: 'prompt_modification',
      timestamp: new Date(now - 5 * 60 * 60 * 1000).toISOString(),
      description: 'System prompt updated to emphasize evidence-based reasoning over rhetoric',
      old_value: 'You are a skilled debater who constructs persuasive arguments...',
      new_value:
        'You are an evidence-based reasoner who builds arguments from verifiable claims...',
      elo_before: 1380,
      elo_after: 1380,
      nomic_cycle_id: 'nomic-041',
      approved: true,
      approved_by: 'system',
    },
    {
      id: 'evt-003',
      agent_name: 'gemini-pro',
      event_type: 'elo_adjustment',
      timestamp: new Date(now - 8 * 60 * 60 * 1000).toISOString(),
      description: 'ELO recalibrated after tournament bracket reset',
      old_value: null,
      new_value: null,
      elo_before: 1350,
      elo_after: 1312,
      nomic_cycle_id: null,
      approved: null,
      approved_by: null,
    },
    {
      id: 'evt-004',
      agent_name: 'mistral-large',
      event_type: 'nomic_proposal',
      timestamp: new Date(now - 12 * 60 * 60 * 1000).toISOString(),
      description:
        'Nomic Loop proposed persona evolution toward "devil\'s advocate" specialization',
      old_value: 'generalist',
      new_value: 'devils_advocate',
      elo_before: 1290,
      elo_after: null,
      nomic_cycle_id: 'nomic-043',
      approved: null,
      approved_by: null,
    },
    {
      id: 'evt-005',
      agent_name: 'claude-3-opus',
      event_type: 'prompt_modification',
      timestamp: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
      description: 'Added structured output formatting directives for consensus synthesis',
      old_value: '...synthesize the discussion into a clear conclusion.',
      new_value:
        '...synthesize the discussion using: 1) Key agreements, 2) Unresolved tensions, 3) Recommended action.',
      elo_before: 1410,
      elo_after: 1420,
      nomic_cycle_id: 'nomic-040',
      approved: true,
      approved_by: 'admin@acme.com',
    },
    {
      id: 'evt-006',
      agent_name: 'grok-2',
      event_type: 'rollback',
      timestamp: new Date(now - 36 * 60 * 60 * 1000).toISOString(),
      description: 'Rolled back persona change after 8% consensus rate drop in last 10 debates',
      old_value: 'aggressive_challenger',
      new_value: 'balanced_critic',
      elo_before: 1260,
      elo_after: 1275,
      nomic_cycle_id: 'nomic-039',
      approved: true,
      approved_by: 'system',
    },
    {
      id: 'evt-007',
      agent_name: 'deepseek-v4-pro',
      event_type: 'persona_change',
      timestamp: new Date(now - 48 * 60 * 60 * 1000).toISOString(),
      description:
        'Graduated from "novice" to "intermediate analyst" after 50 successful debate participations',
      old_value: 'novice',
      new_value: 'intermediate_analyst',
      elo_before: 1180,
      elo_after: 1210,
      nomic_cycle_id: null,
      approved: null,
      approved_by: null,
    },
  ],
  total: 7,
  limit: 20,
  offset: 0,
};

const MOCK_ELO_TRENDS: EloTrendsData = {
  agents: [
    {
      agent_name: 'claude-3-opus',
      provider: 'anthropic',
      current_elo: 1435,
      trend: [
        {
          timestamp: new Date(now - 7 * 86400000).toISOString(),
          elo: 1390,
          debate_id: 'dbt-101',
          change: 12,
        },
        {
          timestamp: new Date(now - 6 * 86400000).toISOString(),
          elo: 1402,
          debate_id: 'dbt-105',
          change: 8,
        },
        {
          timestamp: new Date(now - 5 * 86400000).toISOString(),
          elo: 1410,
          debate_id: 'dbt-112',
          change: -5,
        },
        {
          timestamp: new Date(now - 4 * 86400000).toISOString(),
          elo: 1405,
          debate_id: 'dbt-118',
          change: 15,
        },
        {
          timestamp: new Date(now - 3 * 86400000).toISOString(),
          elo: 1420,
          debate_id: 'dbt-124',
          change: 7,
        },
        {
          timestamp: new Date(now - 2 * 86400000).toISOString(),
          elo: 1427,
          debate_id: 'dbt-130',
          change: 8,
        },
        {
          timestamp: new Date(now - 1 * 86400000).toISOString(),
          elo: 1435,
          debate_id: 'dbt-135',
          change: 0,
        },
      ],
      peak_elo: 1435,
      lowest_elo: 1390,
      total_debates: 47,
    },
    {
      agent_name: 'gpt-4-turbo',
      provider: 'openai',
      current_elo: 1380,
      trend: [
        {
          timestamp: new Date(now - 7 * 86400000).toISOString(),
          elo: 1395,
          debate_id: 'dbt-102',
          change: -8,
        },
        {
          timestamp: new Date(now - 6 * 86400000).toISOString(),
          elo: 1387,
          debate_id: 'dbt-106',
          change: -5,
        },
        {
          timestamp: new Date(now - 5 * 86400000).toISOString(),
          elo: 1382,
          debate_id: 'dbt-113',
          change: 10,
        },
        {
          timestamp: new Date(now - 4 * 86400000).toISOString(),
          elo: 1392,
          debate_id: 'dbt-119',
          change: -12,
        },
        {
          timestamp: new Date(now - 3 * 86400000).toISOString(),
          elo: 1380,
          debate_id: 'dbt-125',
          change: 5,
        },
        {
          timestamp: new Date(now - 2 * 86400000).toISOString(),
          elo: 1385,
          debate_id: 'dbt-131',
          change: -5,
        },
        {
          timestamp: new Date(now - 1 * 86400000).toISOString(),
          elo: 1380,
          debate_id: 'dbt-136',
          change: 0,
        },
      ],
      peak_elo: 1395,
      lowest_elo: 1380,
      total_debates: 52,
    },
    {
      agent_name: 'gemini-pro',
      provider: 'google',
      current_elo: 1312,
      trend: [
        {
          timestamp: new Date(now - 7 * 86400000).toISOString(),
          elo: 1350,
          debate_id: 'dbt-103',
          change: -10,
        },
        {
          timestamp: new Date(now - 6 * 86400000).toISOString(),
          elo: 1340,
          debate_id: 'dbt-107',
          change: -8,
        },
        {
          timestamp: new Date(now - 5 * 86400000).toISOString(),
          elo: 1332,
          debate_id: 'dbt-114',
          change: -5,
        },
        {
          timestamp: new Date(now - 4 * 86400000).toISOString(),
          elo: 1327,
          debate_id: 'dbt-120',
          change: -10,
        },
        {
          timestamp: new Date(now - 3 * 86400000).toISOString(),
          elo: 1317,
          debate_id: 'dbt-126',
          change: -3,
        },
        {
          timestamp: new Date(now - 2 * 86400000).toISOString(),
          elo: 1314,
          debate_id: 'dbt-132',
          change: -2,
        },
        {
          timestamp: new Date(now - 1 * 86400000).toISOString(),
          elo: 1312,
          debate_id: 'dbt-137',
          change: 0,
        },
      ],
      peak_elo: 1350,
      lowest_elo: 1312,
      total_debates: 38,
    },
    {
      agent_name: 'mistral-large',
      provider: 'mistral',
      current_elo: 1290,
      trend: [
        {
          timestamp: new Date(now - 7 * 86400000).toISOString(),
          elo: 1260,
          debate_id: 'dbt-104',
          change: 8,
        },
        {
          timestamp: new Date(now - 6 * 86400000).toISOString(),
          elo: 1268,
          debate_id: 'dbt-108',
          change: 5,
        },
        {
          timestamp: new Date(now - 5 * 86400000).toISOString(),
          elo: 1273,
          debate_id: 'dbt-115',
          change: 7,
        },
        {
          timestamp: new Date(now - 4 * 86400000).toISOString(),
          elo: 1280,
          debate_id: 'dbt-121',
          change: 3,
        },
        {
          timestamp: new Date(now - 3 * 86400000).toISOString(),
          elo: 1283,
          debate_id: 'dbt-127',
          change: 4,
        },
        {
          timestamp: new Date(now - 2 * 86400000).toISOString(),
          elo: 1287,
          debate_id: 'dbt-133',
          change: 3,
        },
        {
          timestamp: new Date(now - 1 * 86400000).toISOString(),
          elo: 1290,
          debate_id: 'dbt-138',
          change: 0,
        },
      ],
      peak_elo: 1290,
      lowest_elo: 1260,
      total_debates: 29,
    },
  ],
  period: '7d',
};

const EMPTY_PENDING_CHANGES: PendingChangesData = { changes: [], total_pending: 0 };

// ============================================================================
// Hooks
// ============================================================================

/**
 * Hook for fetching the agent evolution timeline.
 * Shows persona changes, prompt modifications, ELO adjustments, and Nomic proposals.
 */
export function useAgentEvolution(
  limit: number = 20,
  offset: number = 0,
  options?: UseSWRFetchOptions<{ data: EvolutionTimeline }>,
) {
  const result = useSWRFetch<{ data: EvolutionTimeline }>(
    `/api/v1/agent-evolution/timeline?limit=${limit}&offset=${offset}`,
    { refreshInterval: 30000, ...options },
  );

  return { ...result, timeline: result.data?.data ?? null, timelineFallback: MOCK_TIMELINE };
}

/**
 * Hook for fetching ELO score trends for all agents over time.
 */
export function useAgentEloTrends(
  period: string = '7d',
  options?: UseSWRFetchOptions<{ data: EloTrendsData }>,
) {
  const result = useSWRFetch<{ data: EloTrendsData }>(
    `/api/v1/agent-evolution/elo-trends?period=${period}`,
    { refreshInterval: 60000, ...options },
  );

  return { ...result, trends: result.data?.data ?? null, trendsFallback: MOCK_ELO_TRENDS };
}

/**
 * Hook for fetching pending Nomic Loop changes awaiting admin approval.
 */
export function usePendingChanges(options?: UseSWRFetchOptions<{ data: PendingChangesData }>) {
  const result = useSWRFetch<{ data: PendingChangesData }>('/api/v1/agent-evolution/pending', {
    refreshInterval: 15000,
    ...options,
  });

  return { ...result, pending: result.data?.data ?? null, pendingFallback: EMPTY_PENDING_CHANGES };
}

/**
 * Unified hook for the Agent Evolution dashboard.
 * Combines timeline, ELO trends, and pending changes with action methods.
 */
export function useAgentEvolutionDashboard(period: string = '7d') {
  const {
    timeline,
    timelineFallback,
    isLoading: timelineLoading,
    error: timelineError,
  } = useAgentEvolution();
  const {
    trends,
    trendsFallback,
    isLoading: trendsLoading,
    error: trendsError,
  } = useAgentEloTrends(period);
  const {
    pending,
    pendingFallback,
    isLoading: pendingLoading,
    error: pendingError,
    mutate: mutatePending,
  } = usePendingChanges();

  const api = useApi();

  const isLoading = timelineLoading || trendsLoading || pendingLoading;
  const error = timelineError || trendsError || pendingError;

  // Effective data: backend or fallback
  const effectiveTimeline = timeline ?? timelineFallback;
  const effectiveTrends = trends ?? trendsFallback;
  const effectivePending = pending ?? pendingFallback;

  const approveChange = useCallback(
    async (changeId: string) => {
      await api.post(`/api/v1/agent-evolution/pending/${changeId}/approve`);
      invalidateCache('/api/v1/agent-evolution/pending');
      invalidateCache('/api/v1/agent-evolution/timeline');
      mutatePending();
    },
    [api, mutatePending],
  );

  const rejectChange = useCallback(
    async (changeId: string, reason?: string) => {
      await api.post(`/api/v1/agent-evolution/pending/${changeId}/reject`, { reason });
      invalidateCache('/api/v1/agent-evolution/pending');
      mutatePending();
    },
    [api, mutatePending],
  );

  const refresh = useCallback(() => {
    invalidateCache('/api/v1/agent-evolution/timeline');
    invalidateCache('/api/v1/agent-evolution/elo-trends');
    invalidateCache('/api/v1/agent-evolution/pending');
  }, []);

  return {
    // Data
    timeline: effectiveTimeline,
    trends: effectiveTrends,
    pending: effectivePending,

    // State
    isLoading,
    error,

    // Actions
    approveChange,
    rejectChange,
    refresh,
  };
}

export default useAgentEvolutionDashboard;
