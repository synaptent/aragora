'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  isSupabaseConfigured,
  fetchRecentLoops,
  fetchCyclesForLoop,
  fetchEventsForLoop,
  fetchDebatesForLoop,
  subscribeToEvents,
  subscribeToAllEvents,
  type NomicCycle,
  type StreamEventRow,
  type DebateArtifact,
} from '@/utils/supabase';

export interface HistoryState {
  isConfigured: boolean;
  isLoading: boolean;
  error: string | null;
  recentLoops: string[];
  selectedLoopId: string | null;
  cycles: NomicCycle[];
  events: StreamEventRow[];
  debates: DebateArtifact[];
}

export function useSupabaseHistory() {
  const [state, setState] = useState<HistoryState>({
    isConfigured: isSupabaseConfigured(),
    isLoading: true,
    error: null,
    recentLoops: [],
    selectedLoopId: null,
    cycles: [],
    events: [],
    debates: [],
  });

  // Fetch recent loops on mount
  useEffect(() => {
    if (!state.isConfigured) {
      setState((prev) => ({ ...prev, isLoading: false }));
      return;
    }

    async function loadRecentLoops() {
      try {
        const loops = await fetchRecentLoops(20);
        setState((prev) => ({
          ...prev,
          recentLoops: loops,
          selectedLoopId: loops.length > 0 ? loops[0] : null,
          isLoading: false,
        }));
      } catch (e) {
        setState((prev) => ({ ...prev, error: String(e), isLoading: false }));
      }
    }

    loadRecentLoops();
  }, [state.isConfigured]);

  // Fetch data when selected loop changes
  useEffect(() => {
    if (!state.isConfigured || !state.selectedLoopId) return;

    async function loadLoopData() {
      const loopId = state.selectedLoopId!;
      setState((prev) => ({ ...prev, isLoading: true }));

      try {
        const [cycles, events, debates] = await Promise.all([
          fetchCyclesForLoop(loopId),
          fetchEventsForLoop(loopId),
          fetchDebatesForLoop(loopId),
        ]);

        setState((prev) => ({ ...prev, cycles, events, debates, isLoading: false, error: null }));
      } catch (e) {
        setState((prev) => ({ ...prev, error: String(e), isLoading: false }));
      }
    }

    loadLoopData();
  }, [state.isConfigured, state.selectedLoopId]);

  // Subscribe to real-time events for selected loop
  useEffect(() => {
    if (!state.isConfigured || !state.selectedLoopId) return;

    const unsubscribe = subscribeToEvents(state.selectedLoopId, (newEvent) => {
      setState((prev) => ({ ...prev, events: [...prev.events, newEvent] }));
    });

    return () => {
      if (unsubscribe) unsubscribe();
    };
  }, [state.isConfigured, state.selectedLoopId]);

  // Subscribe to all events to detect new loops
  useEffect(() => {
    if (!state.isConfigured) return;

    const unsubscribe = subscribeToAllEvents((newEvent) => {
      // If this is from a new loop, add it to the list
      if (!state.recentLoops.includes(newEvent.loop_id)) {
        setState((prev) => ({ ...prev, recentLoops: [newEvent.loop_id, ...prev.recentLoops] }));
      }
    });

    return () => {
      if (unsubscribe) unsubscribe();
    };
  }, [state.isConfigured, state.recentLoops]);

  // Select a loop
  const selectLoop = useCallback((loopId: string) => {
    setState((prev) => ({ ...prev, selectedLoopId: loopId, cycles: [], events: [], debates: [] }));
  }, []);

  // Refresh current loop data
  const refresh = useCallback(async () => {
    if (!state.selectedLoopId) return;

    setState((prev) => ({ ...prev, isLoading: true }));

    try {
      const [cycles, events, debates] = await Promise.all([
        fetchCyclesForLoop(state.selectedLoopId),
        fetchEventsForLoop(state.selectedLoopId),
        fetchDebatesForLoop(state.selectedLoopId),
      ]);

      setState((prev) => ({ ...prev, cycles, events, debates, isLoading: false }));
    } catch (e) {
      setState((prev) => ({ ...prev, error: String(e), isLoading: false }));
    }
  }, [state.selectedLoopId]);

  return { ...state, selectLoop, refresh };
}
