'use client';

import { useCallback } from 'react';
import { useSWRFetch } from './useSWRFetch';
import { useApi } from './useApi';
import type { CalibrationData } from '@/components/TrustBadge';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TopAgent {
  id: string;
  elo: number;
  wins: number;
}

export interface RecentImprovement {
  id: string;
  goal: string;
  status: string;
}

export interface SystemOverview {
  totalCycles: number;
  successRate: number;
  activeAgents: number;
  knowledgeItems: number;
  topAgents: TopAgent[];
  recentImprovements: RecentImprovement[];
}

export interface AgentEloHistoryPoint {
  date: string;
  elo: number;
}

export interface AgentPerformanceEntry {
  id: string;
  name: string;
  elo: number;
  eloHistory: AgentEloHistoryPoint[];
  calibration: number;
  calibrationData?: CalibrationData | null;
  winRate: number;
  domains: string[];
}

export interface AgentPerformance {
  agents: AgentPerformanceEntry[];
}

export interface PatternEntry {
  pattern: string;
  frequency: number;
  confidence: number;
}

export interface ConfidenceChange {
  topic: string;
  before: number;
  after: number;
}

export interface InstitutionalMemory {
  totalInjections: number;
  retrievalCount: number;
  topPatterns: PatternEntry[];
  confidenceChanges: ConfidenceChange[];
}

export interface ImprovementQueueItem {
  id: string;
  goal: string;
  priority: number;
  source: string;
  status: string;
  createdAt: string;
}

export interface ImprovementQueueData {
  items: ImprovementQueueItem[];
  totalSize: number;
  sourceBreakdown: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useSystemIntelligence() {
  const { data, error, isLoading, mutate } = useSWRFetch<{ data: SystemOverview }>(
    '/api/v1/system-intelligence/overview',
    { refreshInterval: 30000 },
  );

  return { overview: data?.data ?? null, error, isLoading, refresh: mutate };
}

export function useAgentPerformance() {
  const { data, error, isLoading, mutate } = useSWRFetch<{ data: AgentPerformance }>(
    '/api/v1/system-intelligence/agent-performance',
    { refreshInterval: 60000 },
  );

  return { agents: data?.data?.agents ?? [], error, isLoading, refresh: mutate };
}

export function useInstitutionalMemory() {
  const { data, error, isLoading, mutate } = useSWRFetch<{ data: InstitutionalMemory }>(
    '/api/v1/system-intelligence/institutional-memory',
    { refreshInterval: 60000 },
  );

  return { memory: data?.data ?? null, error, isLoading, refresh: mutate };
}

export function useImprovementQueue() {
  const { data, error, isLoading, mutate } = useSWRFetch<{ data: ImprovementQueueData }>(
    '/api/v1/system-intelligence/improvement-queue',
    { refreshInterval: 15000 },
  );

  const api = useApi();

  const addGoal = useCallback(
    async (goal: string, priority: number = 50) => {
      await api.post('/api/v1/self-improve/improvement-queue', { goal, priority, source: 'user' });
      mutate();
    },
    [api, mutate],
  );

  const reorderItem = useCallback(
    async (id: string, priority: number) => {
      await api.put(`/api/v1/self-improve/improvement-queue/${id}/priority`, { priority });
      mutate();
    },
    [api, mutate],
  );

  const removeItem = useCallback(
    async (id: string) => {
      await api.request(`/api/v1/self-improve/improvement-queue/${id}`, { method: 'DELETE' });
      mutate();
    },
    [api, mutate],
  );

  return {
    queue: data?.data ?? null,
    items: data?.data?.items ?? [],
    error,
    isLoading,
    refresh: mutate,
    addGoal,
    reorderItem,
    removeItem,
  };
}
