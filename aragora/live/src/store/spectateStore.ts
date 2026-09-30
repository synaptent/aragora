'use client';

import { create } from 'zustand';
import { devtools, subscribeWithSelector } from 'zustand/middleware';

// ============================================================================
// Types - Maps to aragora/spectate/events.py
// ============================================================================

export type SpectatorEventType =
  | 'debate_start'
  | 'debate_end'
  | 'round_start'
  | 'round_end'
  | 'proposal'
  | 'critique'
  | 'refine'
  | 'vote'
  | 'judge'
  | 'consensus'
  | 'convergence'
  | 'converged'
  | 'memory_recall'
  | 'breakpoint'
  | 'breakpoint_resolved'
  | 'system'
  | 'error';

export interface SpectatorEvent {
  type: SpectatorEventType;
  timestamp: number;
  agent: string | null;
  details: string | null;
  metric: number | null;
  round: number | null;
}

export type SpectateConnectionStatus =
  'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';

// Event styles for UI - maps to EVENT_STYLES in events.py
// Uses theme-aware Tailwind color classes (see tailwind.config.js) so colors
// adapt to warm/dark/professional themes via CSS variables.
export const EVENT_STYLES: Record<
  SpectatorEventType,
  { icon: string; color: string; label: string }
> = {
  debate_start: { icon: '🎬', color: 'text-purple', label: 'DEBATE START' },
  debate_end: { icon: '🏁', color: 'text-purple', label: 'DEBATE END' },
  round_start: { icon: '⏱️', color: 'text-acid-cyan', label: 'ROUND START' },
  round_end: { icon: '✓', color: 'text-acid-cyan', label: 'ROUND END' },
  proposal: { icon: '💡', color: 'text-acid-cyan', label: 'PROPOSAL' },
  critique: { icon: '🔍', color: 'text-crimson', label: 'CRITIQUE' },
  refine: { icon: '✨', color: 'text-acid-cyan', label: 'REFINE' },
  vote: { icon: '🗳️', color: 'text-warning', label: 'VOTE' },
  judge: { icon: '⚖️', color: 'text-warning', label: 'JUDGE' },
  consensus: { icon: '🤝', color: 'text-success', label: 'CONSENSUS' },
  convergence: { icon: '📊', color: 'text-success', label: 'CONVERGENCE' },
  converged: { icon: '🎉', color: 'text-success', label: 'CONVERGED' },
  memory_recall: { icon: '🧠', color: 'text-acid-cyan', label: 'MEMORY' },
  breakpoint: { icon: '⚠️', color: 'text-warning', label: 'BREAKPOINT' },
  breakpoint_resolved: { icon: '✅', color: 'text-success', label: 'RESOLVED' },
  system: { icon: '⚙️', color: 'text-text-muted', label: 'SYSTEM' },
  error: { icon: '❌', color: 'text-crimson', label: 'ERROR' },
};

// ============================================================================
// Store State
// ============================================================================

interface SpectateState {
  // Connection state
  debateId: string | null;
  connectionStatus: SpectateConnectionStatus;
  error: string | null;

  // Debate metadata
  task: string | null;
  agents: string[];
  currentRound: number;

  // Events
  events: SpectatorEvent[];

  // UI state
  autoScroll: boolean;
  showTimestamps: boolean;
  filterEventTypes: SpectatorEventType[] | null; // null = show all
}

interface SpectateActions {
  // Connection actions
  connect: (debateId: string) => void;
  disconnect: () => void;
  setConnectionStatus: (status: SpectateConnectionStatus) => void;
  setError: (error: string | null) => void;

  // Event actions
  addEvent: (event: SpectatorEvent) => void;
  clearEvents: () => void;

  // Metadata actions
  setTask: (task: string) => void;
  setAgents: (agents: string[]) => void;
  setCurrentRound: (round: number) => void;

  // UI actions
  setAutoScroll: (enabled: boolean) => void;
  setShowTimestamps: (enabled: boolean) => void;
  setFilterEventTypes: (types: SpectatorEventType[] | null) => void;

  // Reset
  reset: () => void;
}

// ============================================================================
// Initial State
// ============================================================================

const initialState: SpectateState = {
  debateId: null,
  connectionStatus: 'idle',
  error: null,
  task: null,
  agents: [],
  currentRound: 0,
  events: [],
  autoScroll: true,
  showTimestamps: true,
  filterEventTypes: null,
};

// ============================================================================
// Store
// ============================================================================

export const useSpectateStore = create<SpectateState & SpectateActions>()(
  devtools(
    subscribeWithSelector((set, get) => ({
      ...initialState,

      // Connection actions
      connect: (debateId: string) => {
        set({ debateId, connectionStatus: 'connecting', error: null, events: [], currentRound: 0 });
      },

      disconnect: () => {
        set({ connectionStatus: 'disconnected' });
      },

      setConnectionStatus: (status: SpectateConnectionStatus) => {
        set({ connectionStatus: status });
      },

      setError: (error: string | null) => {
        set({ error, connectionStatus: error ? 'error' : get().connectionStatus });
      },

      // Event actions
      addEvent: (event: SpectatorEvent) => {
        set((state) => {
          // Update current round if this is a round event
          let currentRound = state.currentRound;
          if (event.type === 'round_start' && event.round !== null) {
            currentRound = event.round;
          }

          // Extract agents from events
          let agents = state.agents;
          if (event.agent && !agents.includes(event.agent)) {
            agents = [...agents, event.agent];
          }

          return { events: [...state.events, event], currentRound, agents };
        });
      },

      clearEvents: () => {
        set({ events: [], currentRound: 0 });
      },

      // Metadata actions
      setTask: (task: string) => {
        set({ task });
      },

      setAgents: (agents: string[]) => {
        set({ agents });
      },

      setCurrentRound: (round: number) => {
        set({ currentRound: round });
      },

      // UI actions
      setAutoScroll: (enabled: boolean) => {
        set({ autoScroll: enabled });
      },

      setShowTimestamps: (enabled: boolean) => {
        set({ showTimestamps: enabled });
      },

      setFilterEventTypes: (types: SpectatorEventType[] | null) => {
        set({ filterEventTypes: types });
      },

      // Reset
      reset: () => {
        set(initialState);
      },
    })),
    { name: 'spectate-store' },
  ),
);

// ============================================================================
// Selectors
// ============================================================================

export const selectFilteredEvents = (state: SpectateState): SpectatorEvent[] => {
  if (!state.filterEventTypes) {
    return state.events;
  }
  return state.events.filter((e) => state.filterEventTypes!.includes(e.type));
};

export const selectEventsByRound = (state: SpectateState, round: number): SpectatorEvent[] => {
  return state.events.filter((e) => e.round === round);
};

export const selectLatestEvent = (state: SpectateState): SpectatorEvent | null => {
  return state.events.length > 0 ? state.events[state.events.length - 1] : null;
};
