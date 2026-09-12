'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useDebateStore } from '@/store';
import type { StreamEvent } from '@/types/events';
import { logger } from '@/utils/logger';

const DEFAULT_WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'wss://api.aragora.ai/ws';

// Reconnection configuration
const MAX_RECONNECT_ATTEMPTS = 15;
const MAX_RECONNECT_DELAY_MS = 30000;
// Stream timeout: 5 min to exceed backend agent timeout (240s) and prevent premature client-side timeouts
const STREAM_TIMEOUT_MS = 300000;

interface UseDebateWebSocketStoreOptions {
  debateId: string;
  wsUrl?: string;
  enabled?: boolean;
}

/**
 * WebSocket hook that uses the Zustand debate store for state management.
 *
 * This is a drop-in replacement for useDebateWebSocket that stores all state
 * in the global Zustand store instead of local component state. Benefits:
 * - State persists across component remounts
 * - Other components can subscribe to debate state without prop drilling
 * - Better performance through Zustand's selective subscriptions
 *
 * @example
 * ```tsx
 * // In component
 * const { sendVote, sendSuggestion, reconnect } = useDebateWebSocketStore({
 *   debateId: 'abc123',
 *   enabled: true,
 * });
 *
 * // In another component, read state directly from store
 * const messages = useDebateStore((state) => state.current.messages);
 * ```
 */
export function useDebateWebSocketStore({
  debateId,
  wsUrl = DEFAULT_WS_URL,
  enabled = true,
}: UseDebateWebSocketStoreOptions) {
  // Get store actions
  const store = useDebateStore();
  const {
    setDebateId,
    setConnectionStatus,
    setError,
    incrementReconnectAttempt,
    resetReconnectAttempt,
    setTask,
    setAgents,
    addAgent,
    addMessage,
    startStream,
    appendStreamToken,
    endStream,
    cleanupOrphanedStreams,
    addStreamEvent,
    clearStreamEvents,
    setHasCitations,
    updateSequence,
  } = store;

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const ackCallbackRef = useRef<((msgType: string) => void) | null>(null);
  const errorCallbackRef = useRef<((message: string) => void) | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isUnmountedRef = useRef(false);
  const cleanupIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Get current state for callbacks
  const reconnectAttempt = useDebateStore((s) => s.current.reconnectAttempt);
  const connectionStatus = useDebateStore((s) => s.current.connectionStatus);

  // Clear reconnection timeout
  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  // Schedule reconnection with exponential backoff
  const scheduleReconnect = useCallback(() => {
    if (isUnmountedRef.current) return;
    if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      setConnectionStatus('error');
      setError(`Connection lost. Max reconnection attempts (${MAX_RECONNECT_ATTEMPTS}) reached.`);
      errorCallbackRef.current?.(`Connection lost after ${MAX_RECONNECT_ATTEMPTS} attempts`);
      return;
    }

    const delay = Math.min(1000 * Math.pow(2, reconnectAttempt), MAX_RECONNECT_DELAY_MS);
    logger.debug(`[WebSocket] Scheduling reconnect attempt ${reconnectAttempt + 1} in ${delay}ms`);

    clearReconnectTimeout();
    reconnectTimeoutRef.current = setTimeout(() => {
      if (!isUnmountedRef.current) {
        incrementReconnectAttempt();
      }
    }, delay);
  }, [
    reconnectAttempt,
    clearReconnectTimeout,
    setConnectionStatus,
    setError,
    incrementReconnectAttempt,
  ]);

  // Manual reconnect trigger
  const reconnect = useCallback(() => {
    clearReconnectTimeout();
    resetReconnectAttempt();
    setConnectionStatus('connecting');
    setError(null);
  }, [clearReconnectTimeout, resetReconnectAttempt, setConnectionStatus, setError]);

  // Send vote
  const sendVote = useCallback(
    (choice: string, intensity?: number) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: 'user_vote',
            debate_id: debateId,
            data: { choice, intensity: intensity ?? 5 },
          }),
        );
      }
    },
    [debateId],
  );

  // Send suggestion
  const sendSuggestion = useCallback(
    (suggestion: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({ type: 'user_suggestion', debate_id: debateId, data: { suggestion } }),
        );
      }
    },
    [debateId],
  );

  // Register callbacks
  const registerAckCallback = useCallback((callback: (msgType: string) => void) => {
    ackCallbackRef.current = callback;
    return () => {
      ackCallbackRef.current = null;
    };
  }, []);

  const registerErrorCallback = useCallback((callback: (message: string) => void) => {
    errorCallbackRef.current = callback;
    return () => {
      errorCallbackRef.current = null;
    };
  }, []);

  // Handle incoming WebSocket message
  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);

        // Track sequence numbers
        if (data.seq && data.seq > 0) {
          const gap = updateSequence(data.seq);
          if (gap) {
            logger.warn(`[WebSocket] Sequence gap detected: ${gap.gap} events missed`);
          }
        }

        // Check if event belongs to this debate
        const eventDebateId = data.loop_id || data.data?.debate_id || data.data?.loop_id;
        const isOurDebate = !eventDebateId || eventDebateId === debateId;
        if (!isOurDebate) return;

        // Handle queue overflow
        if (data.type === 'error' && data.data?.error_type === 'queue_overflow') {
          logger.warn('[WebSocket] Server queue overflow:', data.data.message);
          errorCallbackRef.current?.(
            `Some updates may be missing (${data.data.dropped_count} events dropped)`,
          );
          return;
        }

        // Debate lifecycle events
        if (data.type === 'debate_start') {
          // Only update task if provided and non-empty (don't overwrite with fallback)
          if (data.data.task && data.data.task.trim()) {
            setTask(data.data.task);
          }
          setAgents(data.data.agents || []);
        } else if (data.type === 'debate_end') {
          setConnectionStatus('complete');
        }

        // Agent message events
        else if (data.type === 'debate_message' || data.type === 'agent_message') {
          const msg = {
            agent: data.agent || data.data?.agent || 'unknown',
            role: data.data?.role,
            content: data.data?.content || '',
            round: data.round || data.data?.round,
            timestamp: data.timestamp || data.data?.timestamp || Date.now() / 1000,
          };
          if (msg.content && addMessage(msg)) {
            if (msg.agent) {
              addAgent(msg.agent);
            }
          }

          const streamEvent: StreamEvent = {
            type: 'agent_message',
            data: { agent: msg.agent, content: msg.content, role: data.data?.role || '' },
            timestamp: msg.timestamp,
            round: msg.round,
            agent: msg.agent,
          };
          addStreamEvent(streamEvent);
        }

        // Legacy agent_response events
        else if (data.type === 'agent_response') {
          const msg = {
            agent: data.data?.agent || 'unknown',
            role: data.data?.role,
            content: data.data?.content || data.data?.response || '',
            round: data.data?.round,
            timestamp: Date.now() / 1000,
          };
          if (msg.content) {
            addMessage(msg);
          }
        }

        // Token streaming events
        else if (data.type === 'token_start') {
          const agent = data.agent || data.data?.agent;
          if (agent) {
            startStream(agent);
            addAgent(agent);
          }
        } else if (data.type === 'token_delta') {
          const agent = data.agent || data.data?.agent;
          const token = data.data?.token || '';
          const agentSeq = data.agent_seq || 0;
          if (agent && token) {
            appendStreamToken(agent, token, agentSeq);
          }
        } else if (data.type === 'token_end') {
          const agent = data.agent || data.data?.agent;
          if (agent) {
            endStream(agent);
          }
        }

        // Critique events
        else if (data.type === 'critique') {
          const msg = {
            agent: data.agent || data.data?.agent || 'unknown',
            role: 'critic',
            content: `[CRITIQUE → ${data.data?.target || 'unknown'}] ${data.data?.issues?.join('; ') || data.data?.content || ''}`,
            round: data.round || data.data?.round,
            timestamp: data.timestamp || Date.now() / 1000,
          };
          if (msg.content) {
            addMessage(msg);
          }
        }

        // Consensus events
        else if (data.type === 'consensus') {
          const msg = {
            agent: 'system',
            role: 'synthesizer',
            content: `[CONSENSUS ${data.data?.reached ? 'REACHED' : 'NOT REACHED'}] Confidence: ${Math.round((data.data?.confidence || 0) * 100)}%`,
            timestamp: data.timestamp || Date.now() / 1000,
          };
          addMessage(msg);
        }

        // Acknowledgment events
        else if (data.type === 'ack') {
          ackCallbackRef.current?.(data.data?.message_type || '');
        }

        // Error events
        else if (data.type === 'error') {
          errorCallbackRef.current?.(data.data?.message || 'Unknown error');
        }

        // Stream events (audience, citations, etc.)
        else if (
          [
            'audience_summary',
            'audience_metrics',
            'grounded_verdict',
            'uncertainty_analysis',
            'vote',
            'rhetorical_observation',
            'hollow_consensus',
            'trickster_intervention',
            'memory_recall',
            'flip_detected',
            'evidence_found',
          ].includes(data.type)
        ) {
          const event: StreamEvent = {
            type: data.type,
            data: data.data || {},
            timestamp: data.timestamp || Date.now() / 1000,
            agent: data.agent || data.data?.agent,
            round: data.round || data.data?.round,
          };
          addStreamEvent(event);

          // Mark citations available
          if (
            data.type === 'grounded_verdict' ||
            (data.type === 'evidence_found' && data.data?.count > 0)
          ) {
            setHasCitations(true);
          }
        }
      } catch (e) {
        logger.error('Failed to parse WebSocket message:', e);
      }
    },
    [
      debateId,
      updateSequence,
      setTask,
      setAgents,
      addAgent,
      addMessage,
      startStream,
      appendStreamToken,
      endStream,
      addStreamEvent,
      setConnectionStatus,
      setHasCitations,
    ],
  );

  // Setup orphaned stream cleanup
  useEffect(() => {
    cleanupIntervalRef.current = setInterval(() => {
      cleanupOrphanedStreams(STREAM_TIMEOUT_MS);
    }, 5000);

    return () => {
      if (cleanupIntervalRef.current) {
        clearInterval(cleanupIntervalRef.current);
      }
    };
  }, [cleanupOrphanedStreams]);

  // Clear state on debate end
  useEffect(() => {
    if (connectionStatus === 'complete' || connectionStatus === 'error') {
      clearStreamEvents();
    }
  }, [connectionStatus, clearStreamEvents]);

  // Track unmount
  useEffect(() => {
    isUnmountedRef.current = false;
    return () => {
      isUnmountedRef.current = true;
      clearReconnectTimeout();
    };
  }, [clearReconnectTimeout]);

  // WebSocket connection effect
  useEffect(() => {
    if (!enabled) return;

    // Don't reconnect if max attempts reached
    if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      return;
    }

    // Set debate ID in store
    setDebateId(debateId);
    setConnectionStatus('connecting');

    let ws: WebSocket;

    try {
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;
    } catch (e) {
      logger.error('[WebSocket] Failed to create connection:', e);
      setConnectionStatus('error');
      setError('Failed to establish WebSocket connection');
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      logger.debug(`[WebSocket] Connected (attempt ${reconnectAttempt + 1})`);
      setConnectionStatus('streaming');
      setError(null);
      resetReconnectAttempt();
      ws.send(JSON.stringify({ type: 'subscribe', debate_id: debateId }));
    };

    ws.onmessage = handleMessage;

    ws.onerror = (e) => {
      logger.error('[WebSocket] Connection error:', e);
    };

    ws.onclose = (event) => {
      wsRef.current = null;

      if (
        event.code === 1000 ||
        useDebateStore.getState().current.connectionStatus === 'complete'
      ) {
        setConnectionStatus('complete');
        return;
      }

      logger.warn(`[WebSocket] Connection closed (code: ${event.code})`);

      if (!isUnmountedRef.current) {
        setConnectionStatus('connecting');
        setError(`Connection lost (code: ${event.code}). Reconnecting...`);
        scheduleReconnect();
      }
    };

    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(1000, 'Component unmounted');
      }
    };
  }, [
    enabled,
    wsUrl,
    debateId,
    handleMessage,
    reconnectAttempt,
    scheduleReconnect,
    setDebateId,
    setConnectionStatus,
    setError,
    resetReconnectAttempt,
  ]);

  // Return actions only (state is accessed via store)
  return { sendVote, sendSuggestion, registerAckCallback, registerErrorCallback, reconnect };
}

/**
 * Hook to get debate state from the store.
 * Use this in components that need to read debate state but don't manage the WebSocket.
 */
export function useDebateState() {
  const status = useDebateStore((s) => s.current.connectionStatus);
  const error = useDebateStore((s) => s.current.error);
  const task = useDebateStore((s) => s.current.task);
  const agents = useDebateStore((s) => s.current.agents);
  const messages = useDebateStore((s) => s.current.messages);
  const streamingMessages = useDebateStore((s) => s.current.streamingMessages);
  const streamEvents = useDebateStore((s) => s.current.streamEvents);
  const hasCitations = useDebateStore((s) => s.current.hasCitations);
  const reconnectAttempt = useDebateStore((s) => s.current.reconnectAttempt);

  return {
    status,
    error,
    isConnected: status === 'streaming',
    reconnectAttempt,
    task,
    agents,
    messages,
    streamingMessages,
    streamEvents,
    hasCitations,
  };
}
