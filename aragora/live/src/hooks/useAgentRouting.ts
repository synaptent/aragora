'use client';

import { useState, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

// ============================================================================
// Types
// ============================================================================

export interface AgentRecommendation {
  agent: string;
  score: number;
  expertise: Record<string, number>;
  traits: string[];
  rationale?: string;
}

export interface TeamComposition {
  agents: string[];
  roles: Record<string, string>;
  expected_quality: number;
  diversity_score: number;
}

export interface AutoRouteResult {
  task_id: string;
  detected_domain: Record<string, number>;
  team: TeamComposition;
  rationale: string;
}

export interface DomainScore {
  domain: string;
  confidence: number;
}

export interface TeamCombination {
  agents: string[];
  win_rate: number;
  debates: number;
  avg_consensus_time: number;
}

export interface DomainLeaderboardEntry {
  agent: string;
  score: number;
  wins: number;
  losses: number;
  expertise: Record<string, number>;
}

// ============================================================================
// Hook State
// ============================================================================

interface UseAgentRoutingState {
  recommendations: AgentRecommendation[];
  recommendationsLoading: boolean;
  recommendationsError: string | null;

  autoRouteResult: AutoRouteResult | null;
  autoRouteLoading: boolean;
  autoRouteError: string | null;

  detectedDomains: DomainScore[];
  domainLoading: boolean;
  domainError: string | null;

  bestTeams: TeamCombination[];
  bestTeamsLoading: boolean;
  bestTeamsError: string | null;

  domainLeaderboard: DomainLeaderboardEntry[];
  leaderboardLoading: boolean;
  leaderboardError: string | null;
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Hook for agent routing and team selection
 *
 * @example
 * const routing = useAgentRouting();
 *
 * // Get recommendations for a task
 * await routing.getRecommendations({ primary_domain: 'programming', limit: 5 });
 *
 * // Auto-route a task
 * await routing.autoRoute('Design a REST API for user management');
 *
 * // Detect domain
 * await routing.detectDomain('How should we implement caching?');
 */
export function useAgentRouting() {
  const [state, setState] = useState<UseAgentRoutingState>({
    recommendations: [],
    recommendationsLoading: false,
    recommendationsError: null,
    autoRouteResult: null,
    autoRouteLoading: false,
    autoRouteError: null,
    detectedDomains: [],
    domainLoading: false,
    domainError: null,
    bestTeams: [],
    bestTeamsLoading: false,
    bestTeamsError: null,
    domainLeaderboard: [],
    leaderboardLoading: false,
    leaderboardError: null,
  });

  // ---------------------------------------------------------------------------
  // Get Recommendations
  // ---------------------------------------------------------------------------

  const getRecommendations = useCallback(
    async (
      options: {
        primary_domain?: string;
        secondary_domains?: string[];
        required_traits?: string[];
        task_id?: string;
        limit?: number;
      } = {},
    ): Promise<AgentRecommendation[]> => {
      setState((s) => ({ ...s, recommendationsLoading: true, recommendationsError: null }));

      try {
        const response = await fetch(`${API_BASE}/api/routing/recommendations`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(options),
        });

        if (!response.ok) {
          if (response.status === 503) {
            throw new Error('Agent routing unavailable');
          }
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        const recommendations = data.recommendations || [];
        setState((s) => ({ ...s, recommendationsLoading: false, recommendations }));
        return recommendations;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to get recommendations';
        setState((s) => ({ ...s, recommendationsLoading: false, recommendationsError: errorMsg }));
        return [];
      }
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Auto-Route Task
  // ---------------------------------------------------------------------------

  const autoRoute = useCallback(
    async (
      task: string,
      options: { task_id?: string; exclude?: string[] } = {},
    ): Promise<AutoRouteResult | null> => {
      setState((s) => ({ ...s, autoRouteLoading: true, autoRouteError: null }));

      try {
        const response = await fetch(`${API_BASE}/api/routing/auto-route`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task, ...options }),
        });

        if (!response.ok) {
          if (response.status === 503) {
            throw new Error('Agent routing unavailable');
          }
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        const data: AutoRouteResult = await response.json();
        setState((s) => ({ ...s, autoRouteLoading: false, autoRouteResult: data }));
        return data;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to auto-route task';
        setState((s) => ({ ...s, autoRouteLoading: false, autoRouteError: errorMsg }));
        return null;
      }
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Detect Domain
  // ---------------------------------------------------------------------------

  const detectDomain = useCallback(
    async (task: string, topN: number = 3): Promise<DomainScore[]> => {
      setState((s) => ({ ...s, domainLoading: true, domainError: null }));

      try {
        const response = await fetch(`${API_BASE}/api/routing/detect-domain`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task, top_n: topN }),
        });

        if (!response.ok) {
          if (response.status === 503) {
            throw new Error('Domain detection unavailable');
          }
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        const domains = data.domains || [];
        setState((s) => ({ ...s, domainLoading: false, detectedDomains: domains }));
        return domains;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to detect domain';
        setState((s) => ({ ...s, domainLoading: false, domainError: errorMsg }));
        return [];
      }
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Get Best Teams
  // ---------------------------------------------------------------------------

  const getBestTeams = useCallback(
    async (minDebates: number = 3, limit: number = 10): Promise<TeamCombination[]> => {
      setState((s) => ({ ...s, bestTeamsLoading: true, bestTeamsError: null }));

      try {
        const params = new URLSearchParams({
          min_debates: String(minDebates),
          limit: String(limit),
        });

        const response = await fetch(`${API_BASE}/api/routing/best-teams?${params}`);

        if (!response.ok) {
          if (response.status === 503) {
            throw new Error('Team routing unavailable');
          }
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        const teams = data.combinations || [];
        setState((s) => ({ ...s, bestTeamsLoading: false, bestTeams: teams }));
        return teams;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to get best teams';
        setState((s) => ({ ...s, bestTeamsLoading: false, bestTeamsError: errorMsg }));
        return [];
      }
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Get Domain Leaderboard
  // ---------------------------------------------------------------------------

  const getDomainLeaderboard = useCallback(
    async (domain: string = 'general', limit: number = 10): Promise<DomainLeaderboardEntry[]> => {
      setState((s) => ({ ...s, leaderboardLoading: true, leaderboardError: null }));

      try {
        const params = new URLSearchParams({ domain, limit: String(limit) });

        const response = await fetch(`${API_BASE}/api/routing/domain-leaderboard?${params}`);

        if (!response.ok) {
          if (response.status === 503) {
            throw new Error('Leaderboard unavailable');
          }
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        const leaderboard = data.leaderboard || [];
        setState((s) => ({ ...s, leaderboardLoading: false, domainLeaderboard: leaderboard }));
        return leaderboard;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to get leaderboard';
        setState((s) => ({ ...s, leaderboardLoading: false, leaderboardError: errorMsg }));
        return [];
      }
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Clear State
  // ---------------------------------------------------------------------------

  const clearAutoRoute = useCallback(() => {
    setState((s) => ({
      ...s,
      autoRouteResult: null,
      autoRouteError: null,
      detectedDomains: [],
      domainError: null,
    }));
  }, []);

  const clearErrors = useCallback(() => {
    setState((s) => ({
      ...s,
      recommendationsError: null,
      autoRouteError: null,
      domainError: null,
      bestTeamsError: null,
      leaderboardError: null,
    }));
  }, []);

  // ---------------------------------------------------------------------------
  // Return
  // ---------------------------------------------------------------------------

  return {
    // State
    ...state,

    // Actions
    getRecommendations,
    autoRoute,
    detectDomain,
    getBestTeams,
    getDomainLeaderboard,
    clearAutoRoute,
    clearErrors,

    // Computed
    hasRecommendations: state.recommendations.length > 0,
    hasTeamResult: state.autoRouteResult !== null,
    primaryDomain: state.detectedDomains[0]?.domain ?? 'general',
  };
}
