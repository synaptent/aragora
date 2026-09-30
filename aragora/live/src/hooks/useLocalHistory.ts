'use client';

import { useState, useEffect, useCallback } from 'react';
import { fetchWithRetry } from '@/lib/retry';

interface HistoryCycle {
  id: string;
  cycle_number: number;
  phase: string;
  success: boolean | null;
  timestamp: string;
}

interface HistoryEvent {
  id: string;
  event_type: string;
  agent: string | null;
  timestamp: string;
  event_data: Record<string, unknown>;
}

interface HistoryDebate {
  id: string;
  cycle_number: number;
  phase: string;
  task: string;
  agents: string[];
  consensus_reached: boolean;
  confidence: number;
  timestamp: string;
}

interface HistorySummary {
  total_cycles: number;
  total_debates: number;
  total_events: number;
  consensus_rate: number;
  recent_loop_id: string | null;
}

export interface LocalHistoryState {
  isLoading: boolean;
  error: string | null;
  summary: HistorySummary | null;
  cycles: HistoryCycle[];
  events: HistoryEvent[];
  debates: HistoryDebate[];
}

/**
 * Hook for fetching history from local API endpoints.
 * Use this as a fallback when Supabase is not configured.
 */
export function useLocalHistory(apiBase: string = '') {
  const [state, setState] = useState<LocalHistoryState>({
    isLoading: true,
    error: null,
    summary: null,
    cycles: [],
    events: [],
    debates: [],
  });

  const fetchHistory = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const [summaryRes, cyclesRes, eventsRes, debatesRes] = await Promise.all([
        fetchWithRetry(`${apiBase}/api/history/summary`, undefined, { maxAttempts: 2 }),
        fetchWithRetry(`${apiBase}/api/history/cycles?limit=50`, undefined, { maxAttempts: 2 }),
        fetchWithRetry(`${apiBase}/api/history/events?limit=100`, undefined, { maxAttempts: 2 }),
        fetchWithRetry(`${apiBase}/api/history/debates?limit=20`, undefined, { maxAttempts: 2 }),
      ]);

      const [summary, cyclesData, eventsData, debatesData] = await Promise.all([
        summaryRes.json(),
        cyclesRes.json(),
        eventsRes.json(),
        debatesRes.json(),
      ]);

      setState({
        isLoading: false,
        error: null,
        summary,
        cycles: cyclesData.cycles || [],
        events: eventsData.events || [],
        debates: debatesData.debates || [],
      });
    } catch (e) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: e instanceof Error ? e.message : 'Failed to fetch history',
      }));
    }
  }, [apiBase]);

  // Fetch on mount
  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  return { ...state, refresh: fetchHistory };
}
