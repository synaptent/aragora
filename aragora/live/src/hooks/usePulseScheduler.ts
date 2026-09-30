'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

const API_BASE = API_BASE_URL;

// ============================================================================
// Types
// ============================================================================

export type SchedulerState = 'stopped' | 'running' | 'paused';

export interface SchedulerConfig {
  poll_interval_seconds: number;
  platforms: string[];
  max_debates_per_hour: number;
  min_interval_between_debates: number;
  min_volume_threshold: number;
  min_controversy_score: number;
  allowed_categories: string[];
  blocked_categories: string[];
  dedup_window_hours: number;
  debate_rounds: number;
  consensus_threshold: number;
}

export interface SchedulerMetrics {
  polls_completed: number;
  topics_evaluated: number;
  topics_filtered: number;
  debates_created: number;
  debates_failed: number;
  duplicates_skipped: number;
  last_poll_at: number | null;
  last_debate_at: number | null;
  uptime_seconds: number | null;
}

export interface SchedulerStatus {
  state: SchedulerState;
  run_id: string;
  config: SchedulerConfig;
  metrics: SchedulerMetrics;
  store_analytics?: {
    total_debates: number;
    consensus_rate: number;
    avg_confidence: number;
    by_platform: Record<string, number>;
  };
}

export interface ScheduledDebate {
  id: string;
  topic: string;
  platform: string;
  category: string;
  volume: number;
  debate_id: string | null;
  created_at: number;
  hours_ago: number;
  consensus_reached: boolean | null;
  confidence: number | null;
  rounds_used: number;
  scheduler_run_id: string;
}

export interface SchedulerHistory {
  debates: ScheduledDebate[];
  count: number;
  total: number;
  limit: number;
  offset: number;
}

// ============================================================================
// Hook State
// ============================================================================

interface UsePulseSchedulerState {
  status: SchedulerStatus | null;
  statusLoading: boolean;
  statusError: string | null;

  history: ScheduledDebate[];
  historyLoading: boolean;
  historyError: string | null;
  historyTotal: number;

  actionLoading: boolean;
  actionError: string | null;
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Hook for managing the Pulse Debate Scheduler
 *
 * @example
 * const scheduler = usePulseScheduler();
 *
 * // Get status
 * scheduler.fetchStatus();
 *
 * // Start/stop scheduler
 * scheduler.start();
 * scheduler.stop();
 *
 * // Update config
 * scheduler.updateConfig({ max_debates_per_hour: 10 });
 */
export function usePulseScheduler() {
  const { tokens, isAuthenticated, isLoading: authLoading } = useAuth();
  const [state, setState] = useState<UsePulseSchedulerState>({
    status: null,
    statusLoading: false,
    statusError: null,
    history: [],
    historyLoading: false,
    historyError: null,
    historyTotal: 0,
    actionLoading: false,
    actionError: null,
  });

  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  const getAuthHeaders = useCallback((): HeadersInit | null => {
    if (authLoading || !isAuthenticated || !tokens?.access_token) {
      return null;
    }
    return { 'Content-Type': 'application/json', Authorization: `Bearer ${tokens.access_token}` };
  }, [authLoading, isAuthenticated, tokens?.access_token]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, [getAuthHeaders]);

  // ---------------------------------------------------------------------------
  // Fetch Status
  // ---------------------------------------------------------------------------

  const fetchStatus = useCallback(async (): Promise<SchedulerStatus | null> => {
    setState((s) => ({ ...s, statusLoading: true, statusError: null }));

    try {
      const headers = getAuthHeaders();
      if (!headers) {
        setState((s) => ({ ...s, statusLoading: false, statusError: 'Authentication required' }));
        return null;
      }
      const response = await fetch(`${API_BASE}/api/pulse/scheduler/status`, { headers });

      if (!response.ok) {
        if (response.status === 503) {
          setState((s) => ({ ...s, statusLoading: false, statusError: 'Scheduler unavailable' }));
          return null;
        }
        throw new Error(`HTTP ${response.status}`);
      }

      const data: SchedulerStatus = await response.json();
      setState((s) => ({ ...s, statusLoading: false, statusError: null, status: data }));
      return data;
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : 'Failed to fetch status';
      setState((s) => ({ ...s, statusLoading: false, statusError: errorMsg }));
      return null;
    }
  }, [getAuthHeaders]);

  // ---------------------------------------------------------------------------
  // Poll Status
  // ---------------------------------------------------------------------------

  const startPolling = useCallback(
    (intervalMs: number = 30000) => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }

      fetchStatus();

      pollingRef.current = setInterval(() => {
        fetchStatus();
      }, intervalMs);
    },
    [fetchStatus],
  );

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Scheduler Actions
  // ---------------------------------------------------------------------------

  const start = useCallback(async (): Promise<boolean> => {
    setState((s) => ({ ...s, actionLoading: true, actionError: null }));

    try {
      const headers = getAuthHeaders();
      if (!headers) {
        setState((s) => ({ ...s, actionLoading: false, actionError: 'Authentication required' }));
        return false;
      }
      const response = await fetch(`${API_BASE}/api/pulse/scheduler/start`, {
        method: 'POST',
        headers,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }

      await fetchStatus();
      setState((s) => ({ ...s, actionLoading: false }));
      return true;
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : 'Failed to start scheduler';
      setState((s) => ({ ...s, actionLoading: false, actionError: errorMsg }));
      return false;
    }
  }, [fetchStatus, getAuthHeaders]);

  const stop = useCallback(
    async (graceful: boolean = true): Promise<boolean> => {
      setState((s) => ({ ...s, actionLoading: true, actionError: null }));

      try {
        const headers = getAuthHeaders();
        if (!headers) {
          setState((s) => ({ ...s, actionLoading: false, actionError: 'Authentication required' }));
          return false;
        }
        const response = await fetch(`${API_BASE}/api/pulse/scheduler/stop`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ graceful }),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        await fetchStatus();
        setState((s) => ({ ...s, actionLoading: false }));
        return true;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to stop scheduler';
        setState((s) => ({ ...s, actionLoading: false, actionError: errorMsg }));
        return false;
      }
    },
    [fetchStatus, getAuthHeaders],
  );

  const pause = useCallback(async (): Promise<boolean> => {
    setState((s) => ({ ...s, actionLoading: true, actionError: null }));

    try {
      const headers = getAuthHeaders();
      if (!headers) {
        setState((s) => ({ ...s, actionLoading: false, actionError: 'Authentication required' }));
        return false;
      }
      const response = await fetch(`${API_BASE}/api/pulse/scheduler/pause`, {
        method: 'POST',
        headers,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }

      await fetchStatus();
      setState((s) => ({ ...s, actionLoading: false }));
      return true;
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : 'Failed to pause scheduler';
      setState((s) => ({ ...s, actionLoading: false, actionError: errorMsg }));
      return false;
    }
  }, [fetchStatus, getAuthHeaders]);

  const resume = useCallback(async (): Promise<boolean> => {
    setState((s) => ({ ...s, actionLoading: true, actionError: null }));

    try {
      const headers = getAuthHeaders();
      if (!headers) {
        setState((s) => ({ ...s, actionLoading: false, actionError: 'Authentication required' }));
        return false;
      }
      const response = await fetch(`${API_BASE}/api/pulse/scheduler/resume`, {
        method: 'POST',
        headers,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }

      await fetchStatus();
      setState((s) => ({ ...s, actionLoading: false }));
      return true;
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : 'Failed to resume scheduler';
      setState((s) => ({ ...s, actionLoading: false, actionError: errorMsg }));
      return false;
    }
  }, [fetchStatus, getAuthHeaders]);

  // ---------------------------------------------------------------------------
  // Update Config
  // ---------------------------------------------------------------------------

  const updateConfig = useCallback(
    async (updates: Partial<SchedulerConfig>): Promise<boolean> => {
      setState((s) => ({ ...s, actionLoading: true, actionError: null }));

      try {
        const headers = getAuthHeaders();
        if (!headers) {
          setState((s) => ({ ...s, actionLoading: false, actionError: 'Authentication required' }));
          return false;
        }
        const response = await fetch(`${API_BASE}/api/pulse/scheduler/config`, {
          method: 'PATCH',
          headers,
          body: JSON.stringify(updates),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        await fetchStatus();
        setState((s) => ({ ...s, actionLoading: false }));
        return true;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to update config';
        setState((s) => ({ ...s, actionLoading: false, actionError: errorMsg }));
        return false;
      }
    },
    [fetchStatus, getAuthHeaders],
  );

  // ---------------------------------------------------------------------------
  // Fetch History
  // ---------------------------------------------------------------------------

  const fetchHistory = useCallback(
    async (
      limit: number = 50,
      offset: number = 0,
      platform?: string,
    ): Promise<ScheduledDebate[]> => {
      setState((s) => ({ ...s, historyLoading: true, historyError: null }));

      try {
        const headers = getAuthHeaders();
        if (!headers) {
          setState((s) => ({
            ...s,
            historyLoading: false,
            historyError: 'Authentication required',
          }));
          return [];
        }
        const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
        if (platform) {
          params.set('platform', platform);
        }

        const response = await fetch(`${API_BASE}/api/pulse/scheduler/history?${params}`, {
          headers,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data: SchedulerHistory = await response.json();
        setState((s) => ({
          ...s,
          historyLoading: false,
          historyError: null,
          history: data.debates,
          historyTotal: data.total,
        }));
        return data.debates;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to fetch history';
        setState((s) => ({ ...s, historyLoading: false, historyError: errorMsg }));
        return [];
      }
    },
    [getAuthHeaders],
  );

  // ---------------------------------------------------------------------------
  // Clear Errors
  // ---------------------------------------------------------------------------

  const clearErrors = useCallback(() => {
    setState((s) => ({ ...s, statusError: null, historyError: null, actionError: null }));
  }, []);

  // ---------------------------------------------------------------------------
  // Return
  // ---------------------------------------------------------------------------

  return {
    // State
    ...state,
    isPolling: pollingRef.current !== null,

    // Status shortcuts
    isRunning: state.status?.state === 'running',
    isPaused: state.status?.state === 'paused',
    isStopped: state.status?.state === 'stopped',
    config: state.status?.config ?? null,
    metrics: state.status?.metrics ?? null,

    // Actions
    fetchStatus,
    startPolling,
    stopPolling,
    start,
    stop,
    pause,
    resume,
    updateConfig,
    fetchHistory,
    clearErrors,
  };
}
