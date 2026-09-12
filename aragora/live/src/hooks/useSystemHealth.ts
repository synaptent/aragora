'use client';

import { useSWRFetch, type UseSWRFetchOptions } from './useSWRFetch';

// ============================================================================
// Types
// ============================================================================

export interface CircuitBreakerInfo {
  name: string;
  state: 'closed' | 'open' | 'half-open';
  failure_count: number;
  failure_threshold: number;
  cooldown_seconds: number;
  success_rate: number;
  last_failure: string | null;
}

export interface SLOInfo {
  name: string;
  key: string;
  target: number;
  current: number;
  compliant: boolean;
  compliance_percentage: number;
  error_budget_remaining: number;
  burn_rate: number;
}

export interface AdapterInfo {
  name: string;
  enabled_by_default: boolean;
  priority: number;
  has_reverse_sync: boolean;
}

export interface AgentInfo {
  agent_id: string;
  type: string;
  status: 'active' | 'idle' | 'failed' | string;
  last_heartbeat: string;
}

export interface BudgetForecast {
  eom: number;
  trend: 'increasing' | 'stable' | 'decreasing';
}

export interface BudgetInfo {
  total_budget: number;
  spent: number;
  utilization: number;
  forecast: BudgetForecast | null;
  available: boolean;
}

export interface SubsystemHealth {
  breakers: CircuitBreakerInfo[];
  total: number;
  available: boolean;
}

export interface SLOHealth {
  slos: SLOInfo[];
  overall_healthy: boolean;
  timestamp?: string;
  available: boolean;
}

export interface AdapterHealth {
  adapters: AdapterInfo[];
  active: number;
  total: number;
  available: boolean;
}

export interface AgentPoolHealth {
  agents: AgentInfo[];
  total: number;
  active: number;
  available: boolean;
}

export interface SystemHealthOverview {
  overall_status: 'healthy' | 'degraded' | 'critical';
  subsystems: Record<string, string>;
  circuit_breakers: SubsystemHealth;
  slos: SLOHealth;
  adapters: AdapterHealth;
  agents: AgentPoolHealth;
  budget: BudgetInfo;
  last_check: string;
  collection_time_ms: number;
}

// ============================================================================
// Hooks
// ============================================================================

export function useSystemHealth(options?: UseSWRFetchOptions<{ data: SystemHealthOverview }>) {
  const result = useSWRFetch<{ data: SystemHealthOverview }>('/api/admin/system-health', {
    refreshInterval: 30000,
    ...options,
  });

  return { ...result, health: result.data?.data ?? null };
}

export function useCircuitBreakers(options?: UseSWRFetchOptions<{ data: SubsystemHealth }>) {
  const result = useSWRFetch<{ data: SubsystemHealth }>(
    '/api/admin/system-health/circuit-breakers',
    { refreshInterval: 15000, ...options },
  );

  return {
    ...result,
    breakers: result.data?.data?.breakers ?? [],
    available: result.data?.data?.available ?? false,
  };
}

export function useSLOStatus(options?: UseSWRFetchOptions<{ data: SLOHealth }>) {
  const result = useSWRFetch<{ data: SLOHealth }>('/api/admin/system-health/slos', {
    refreshInterval: 30000,
    ...options,
  });

  return {
    ...result,
    slos: result.data?.data?.slos ?? [],
    overallHealthy: result.data?.data?.overall_healthy ?? true,
    available: result.data?.data?.available ?? false,
  };
}

export function useAgentPoolHealth(options?: UseSWRFetchOptions<{ data: AgentPoolHealth }>) {
  const result = useSWRFetch<{ data: AgentPoolHealth }>('/api/admin/system-health/agents', {
    refreshInterval: 30000,
    ...options,
  });

  return {
    ...result,
    agents: result.data?.data?.agents ?? [],
    total: result.data?.data?.total ?? 0,
    active: result.data?.data?.active ?? 0,
    available: result.data?.data?.available ?? false,
  };
}

export function useBudgetStatus(options?: UseSWRFetchOptions<{ data: BudgetInfo }>) {
  const result = useSWRFetch<{ data: BudgetInfo }>('/api/admin/system-health/budget', {
    refreshInterval: 60000,
    ...options,
  });

  return {
    ...result,
    budget: result.data?.data ?? null,
    available: result.data?.data?.available ?? false,
  };
}
