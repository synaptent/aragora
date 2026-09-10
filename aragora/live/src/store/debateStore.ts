'use client';

import { create } from 'zustand';
import { devtools, subscribeWithSelector } from 'zustand/middleware';
import type { StreamEvent } from '@/types/events';
import type { DebateConnectionStatus } from '@/hooks/useDebateWebSocket';

// ============================================================================
// Types
// ============================================================================

export interface TranscriptMessage {
  agent: string;
  role?: string;
  content: string;
  round?: number;
  timestamp?: number;
}

export interface ReasoningStep {
  thinking: string;
  timestamp: number;
  step?: number;
}

export interface EvidenceSource {
  title: string;
  url?: string;
  relevance?: number;
}

export interface StreamingMessage {
  agent: string;
  taskId: string; // Task ID for composite React key support
  content: string;
  isComplete: boolean;
  startTime: number;
  expectedSeq: number;
  pendingTokens: Map<number, string>;
  reasoning: ReasoningStep[];
  evidence: EvidenceSource[];
  confidence: number | null;
}

export type { DebateConnectionStatus } from '@/hooks/useDebateWebSocket';

export interface DebateArtifact {
  id: string;
  task: string;
  agents: string[];
  consensus_reached: boolean;
  confidence: number;
  created_at: string;
  transcript?: TranscriptMessage[];
}

// ============================================================================
// Store State
// ============================================================================

interface DebateState {
  // Current live debate session
  current: {
    debateId: string | null;
    task: string;
    agents: string[];
    messages: TranscriptMessage[];
    streamingMessages: Map<string, StreamingMessage>;
    streamEvents: StreamEvent[];
    hasCitations: boolean;
    connectionStatus: DebateConnectionStatus;
    error: string | null;
    reconnectAttempt: number;
  };

  // Loaded debate artifact (for viewing completed debates)
  artifact: DebateArtifact | null;

  // UI state
  ui: {
    showParticipation: boolean;
    showCitations: boolean;
    userScrolled: boolean;
    autoScroll: boolean;
  };

  // Deduplication tracking (internal)
  _seenMessages: Set<string>;
  _lastSeq: number;
}

interface DebateActions {
  // Connection actions
  setDebateId: (id: string | null) => void;
  setConnectionStatus: (status: DebateConnectionStatus) => void;
  setError: (error: string | null) => void;
  incrementReconnectAttempt: () => void;
  resetReconnectAttempt: () => void;

  // Debate data actions
  setTask: (task: string) => void;
  setAgents: (agents: string[]) => void;
  addAgent: (agent: string) => void;

  // Message actions
  addMessage: (message: TranscriptMessage) => boolean;
  clearMessages: () => void;

  // Streaming actions
  startStream: (agent: string, taskId?: string) => void;
  appendStreamToken: (agent: string, token: string, agentSeq?: number, taskId?: string) => void;
  endStream: (agent: string, taskId?: string) => void;
  cleanupOrphanedStreams: (timeoutMs: number) => void;

  // Stream events
  addStreamEvent: (event: StreamEvent) => void;
  clearStreamEvents: () => void;
  setHasCitations: (has: boolean) => void;

  // Artifact actions
  setArtifact: (artifact: DebateArtifact | null) => void;

  // UI actions
  setShowParticipation: (show: boolean) => void;
  setShowCitations: (show: boolean) => void;
  setUserScrolled: (scrolled: boolean) => void;
  setAutoScroll: (auto: boolean) => void;

  // Sequence tracking
  updateSequence: (seq: number) => { gap: number } | null;

  // Reset
  resetCurrent: () => void;
  resetAll: () => void;
}

type DebateStore = DebateState & DebateActions;

// ============================================================================
// Constants
// ============================================================================

const MAX_STREAM_EVENTS = 500;

const initialCurrentState = {
  debateId: null,
  task: '',
  agents: [],
  messages: [],
  streamingMessages: new Map<string, StreamingMessage>(),
  streamEvents: [],
  hasCitations: false,
  connectionStatus: 'idle' as DebateConnectionStatus,
  error: null,
  reconnectAttempt: 0,
};

const initialUIState = {
  showParticipation: false,
  showCitations: false,
  userScrolled: false,
  autoScroll: true,
};

// ============================================================================
// Store Implementation
// ============================================================================

export const useDebateStore = create<DebateStore>()(
  devtools(
    subscribeWithSelector((set, get) => ({
      // Initial state
      current: { ...initialCurrentState },
      artifact: null,
      ui: { ...initialUIState },
      _seenMessages: new Set<string>(),
      _lastSeq: 0,

      // Connection actions
      setDebateId: (id) =>
        set((state) => ({ current: { ...state.current, debateId: id } }), false, 'setDebateId'),

      setConnectionStatus: (status) =>
        set(
          (state) => ({ current: { ...state.current, connectionStatus: status } }),
          false,
          'setConnectionStatus',
        ),

      setError: (error) =>
        set((state) => ({ current: { ...state.current, error } }), false, 'setError'),

      incrementReconnectAttempt: () =>
        set(
          (state) => ({
            current: { ...state.current, reconnectAttempt: state.current.reconnectAttempt + 1 },
          }),
          false,
          'incrementReconnectAttempt',
        ),

      resetReconnectAttempt: () =>
        set(
          (state) => ({ current: { ...state.current, reconnectAttempt: 0 } }),
          false,
          'resetReconnectAttempt',
        ),

      // Debate data actions
      setTask: (task) =>
        set((state) => ({ current: { ...state.current, task } }), false, 'setTask'),

      setAgents: (agents) =>
        set((state) => ({ current: { ...state.current, agents } }), false, 'setAgents'),

      addAgent: (agent) =>
        set(
          (state) => {
            if (state.current.agents.includes(agent)) return state;
            return { current: { ...state.current, agents: [...state.current.agents, agent] } };
          },
          false,
          'addAgent',
        ),

      // Message actions with deduplication
      addMessage: (message) => {
        const state = get();
        // Use agent + round + first 120 chars for dedup key (avoids hash
        // collisions from truncation while keeping key size bounded)
        const msgKey = `${message.agent}-r${message.round ?? 0}-${message.content.slice(0, 120)}`;

        if (state._seenMessages.has(msgKey)) {
          return false;
        }

        set(
          (s) => {
            const newSeen = new Set(s._seenMessages);
            newSeen.add(msgKey);
            return {
              current: { ...s.current, messages: [...s.current.messages, message] },
              _seenMessages: newSeen,
            };
          },
          false,
          'addMessage',
        );

        return true;
      },

      clearMessages: () =>
        set(
          (state) => ({
            current: { ...state.current, messages: [] },
            _seenMessages: new Set<string>(),
          }),
          false,
          'clearMessages',
        ),

      // Streaming actions
      startStream: (agent, taskId = '') =>
        set(
          (state) => {
            const updated = new Map(state.current.streamingMessages);
            // Use composite key if taskId provided, otherwise just agent
            const key = taskId ? `${agent}:${taskId}` : agent;
            updated.set(key, {
              agent,
              taskId,
              content: '',
              isComplete: false,
              startTime: Date.now(),
              expectedSeq: 1,
              pendingTokens: new Map(),
              reasoning: [],
              evidence: [],
              confidence: null,
            });
            return { current: { ...state.current, streamingMessages: updated } };
          },
          false,
          'startStream',
        ),

      appendStreamToken: (agent, token, agentSeq, taskId = '') =>
        set(
          (state) => {
            const updated = new Map(state.current.streamingMessages);
            // Use composite key if taskId provided, otherwise just agent
            const key = taskId ? `${agent}:${taskId}` : agent;
            const existing = updated.get(key);

            if (existing) {
              if (agentSeq && agentSeq > 0) {
                // Sequence-based ordering
                if (agentSeq === existing.expectedSeq) {
                  let newContent = existing.content + token;
                  let nextExpected = agentSeq + 1;
                  const pending = new Map(existing.pendingTokens);

                  while (pending.has(nextExpected)) {
                    newContent += pending.get(nextExpected)!;
                    pending.delete(nextExpected);
                    nextExpected++;
                  }

                  updated.set(key, {
                    ...existing,
                    content: newContent,
                    expectedSeq: nextExpected,
                    pendingTokens: pending,
                  });
                } else if (agentSeq > existing.expectedSeq) {
                  const pending = new Map(existing.pendingTokens);
                  pending.set(agentSeq, token);
                  updated.set(key, { ...existing, pendingTokens: pending });
                }
              } else {
                // Simple append (no sequence)
                updated.set(key, { ...existing, content: existing.content + token });
              }
            } else {
              // New stream without token_start
              updated.set(key, {
                agent,
                taskId,
                content: token,
                isComplete: false,
                startTime: Date.now(),
                expectedSeq: agentSeq && agentSeq > 0 ? agentSeq + 1 : 1,
                pendingTokens: new Map(),
                reasoning: [],
                evidence: [],
                confidence: null,
              });
            }

            return { current: { ...state.current, streamingMessages: updated } };
          },
          false,
          'appendStreamToken',
        ),

      endStream: (agent, taskId = '') => {
        const state = get();
        // Use composite key if taskId provided, otherwise just agent
        const key = taskId ? `${agent}:${taskId}` : agent;
        const existing = state.current.streamingMessages.get(key);

        if (existing) {
          // Flush pending tokens
          let finalContent = existing.content;
          if (existing.pendingTokens.size > 0) {
            const sortedSeqs = Array.from(existing.pendingTokens.keys()).sort((a, b) => a - b);
            for (const seq of sortedSeqs) {
              finalContent += existing.pendingTokens.get(seq)!;
            }
          }

          // Add as completed message
          if (finalContent) {
            const msg: TranscriptMessage = {
              agent: existing.agent, // Use agent from existing, not the key
              content: finalContent,
              timestamp: Date.now() / 1000,
            };
            get().addMessage(msg);
          }
        }

        // Remove from streaming
        set(
          (s) => {
            const updated = new Map(s.current.streamingMessages);
            updated.delete(key);
            return { current: { ...s.current, streamingMessages: updated } };
          },
          false,
          'endStream',
        );
      },

      cleanupOrphanedStreams: (timeoutMs) =>
        set(
          (state) => {
            const now = Date.now();
            const updated = new Map(state.current.streamingMessages);
            let changed = false;
            const messagesToAdd: TranscriptMessage[] = [];

            for (const [agent, msg] of Array.from(updated.entries())) {
              if (now - msg.startTime > timeoutMs) {
                if (msg.content) {
                  messagesToAdd.push({
                    agent: msg.agent,
                    content: msg.content + ' [stream timed out]',
                    timestamp: Date.now() / 1000,
                  });
                }
                updated.delete(agent);
                changed = true;
              }
            }

            if (!changed) return state;

            // Add timed out messages
            const newSeen = new Set(state._seenMessages);
            const newMessages = [...state.current.messages];

            for (const msg of messagesToAdd) {
              const msgKey = `${msg.agent}-${msg.timestamp}-${msg.content.slice(0, 50)}`;
              if (!newSeen.has(msgKey)) {
                newSeen.add(msgKey);
                newMessages.push(msg);
              }
            }

            return {
              current: { ...state.current, streamingMessages: updated, messages: newMessages },
              _seenMessages: newSeen,
            };
          },
          false,
          'cleanupOrphanedStreams',
        ),

      // Stream events
      addStreamEvent: (event) =>
        set(
          (state) => {
            const events = [...state.current.streamEvents, event];
            return {
              current: {
                ...state.current,
                streamEvents:
                  events.length > MAX_STREAM_EVENTS ? events.slice(-MAX_STREAM_EVENTS) : events,
              },
            };
          },
          false,
          'addStreamEvent',
        ),

      clearStreamEvents: () =>
        set(
          (state) => ({ current: { ...state.current, streamEvents: [] } }),
          false,
          'clearStreamEvents',
        ),

      setHasCitations: (has) =>
        set(
          (state) => ({ current: { ...state.current, hasCitations: has } }),
          false,
          'setHasCitations',
        ),

      // Artifact actions
      setArtifact: (artifact) => set({ artifact }, false, 'setArtifact'),

      // UI actions
      setShowParticipation: (show) =>
        set(
          (state) => ({ ui: { ...state.ui, showParticipation: show } }),
          false,
          'setShowParticipation',
        ),

      setShowCitations: (show) =>
        set((state) => ({ ui: { ...state.ui, showCitations: show } }), false, 'setShowCitations'),

      setUserScrolled: (scrolled) =>
        set((state) => ({ ui: { ...state.ui, userScrolled: scrolled } }), false, 'setUserScrolled'),

      setAutoScroll: (auto) =>
        set((state) => ({ ui: { ...state.ui, autoScroll: auto } }), false, 'setAutoScroll'),

      // Sequence tracking
      updateSequence: (seq) => {
        const state = get();
        let gap: { gap: number } | null = null;

        if (state._lastSeq > 0 && seq > state._lastSeq + 1) {
          gap = { gap: seq - state._lastSeq - 1 };
        }

        set({ _lastSeq: seq }, false, 'updateSequence');
        return gap;
      },

      // Reset
      resetCurrent: () =>
        set(
          {
            current: { ...initialCurrentState, streamingMessages: new Map() },
            _seenMessages: new Set<string>(),
            _lastSeq: 0,
          },
          false,
          'resetCurrent',
        ),

      resetAll: () =>
        set(
          {
            current: { ...initialCurrentState, streamingMessages: new Map() },
            artifact: null,
            ui: { ...initialUIState },
            _seenMessages: new Set<string>(),
            _lastSeq: 0,
          },
          false,
          'resetAll',
        ),
    })),
    { name: 'debate-store' },
  ),
);

// ============================================================================
// Selectors (for optimized subscriptions)
// ============================================================================

export const selectDebateStatus = (state: DebateStore) => state.current.connectionStatus;
export const selectDebateMessages = (state: DebateStore) => state.current.messages;
export const selectStreamingMessages = (state: DebateStore) => state.current.streamingMessages;
export const selectDebateAgents = (state: DebateStore) => state.current.agents;
export const selectDebateTask = (state: DebateStore) => state.current.task;
export const selectStreamEvents = (state: DebateStore) => state.current.streamEvents;
export const selectHasCitations = (state: DebateStore) => state.current.hasCitations;
export const selectDebateUI = (state: DebateStore) => state.ui;
export const selectArtifact = (state: DebateStore) => state.artifact;
