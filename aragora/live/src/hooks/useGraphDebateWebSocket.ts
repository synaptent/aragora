'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { logger } from '@/utils/logger';

const DEFAULT_WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'wss://api.aragora.ai/ws';

// Reconnection configuration
const MAX_RECONNECT_ATTEMPTS = 15;
const MAX_RECONNECT_DELAY_MS = 30000; // 30 seconds cap
const MAX_HANDSHAKE_FAILURES = 3;

// Graph debate event types
export type GraphEventType =
  | 'graph_node_added'
  | 'graph_branch_created'
  | 'graph_branch_merged'
  | 'graph_debate_complete'
  | 'debate_branch'
  | 'debate_merge';

export interface GraphDebateEvent {
  type: GraphEventType;
  data: {
    debate_id?: string;
    node_id?: string;
    node_type?: string;
    agent_id?: string;
    content?: string;
    branch_id?: string;
    branch_name?: string;
    parent_ids?: string[];
    confidence?: number;
    merged_branch_ids?: string[];
    synthesis?: string;
    [key: string]: unknown;
  };
  timestamp: number;
  seq?: number;
}

export type GraphConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface UseGraphDebateWebSocketOptions {
  debateId?: string | null;
  wsUrl?: string;
  enabled?: boolean;
  autoReconnect?: boolean;
}

interface UseGraphDebateWebSocketReturn {
  status: GraphConnectionStatus;
  error: string | null;
  isConnected: boolean;
  reconnectAttempt: number; // Expose for UI feedback
  events: GraphDebateEvent[];
  lastEvent: GraphDebateEvent | null;
  reconnect: () => void;
  clearEvents: () => void;
}

export function useGraphDebateWebSocket({
  debateId,
  wsUrl = DEFAULT_WS_URL,
  enabled = true,
  autoReconnect = true,
}: UseGraphDebateWebSocketOptions): UseGraphDebateWebSocketReturn {
  const [status, setStatus] = useState<GraphConnectionStatus>('disconnected');
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<GraphDebateEvent[]>([]);
  const [lastEvent, setLastEvent] = useState<GraphDebateEvent | null>(null);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isUnmountedRef = useRef(false);
  const hasEverConnectedRef = useRef(false);
  const handshakeFailuresRef = useRef(0);

  // Clear any pending reconnection timeout
  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  // Schedule reconnection with exponential backoff
  const scheduleReconnect = useCallback(() => {
    if (isUnmountedRef.current || !autoReconnect) return;
    if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      setStatus('error');
      setError(`Connection lost. Max reconnection attempts (${MAX_RECONNECT_ATTEMPTS}) reached.`);
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, 16s (capped at 30s)
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempt), MAX_RECONNECT_DELAY_MS);
    logger.debug(
      `[Graph WebSocket] Scheduling reconnect attempt ${reconnectAttempt + 1} in ${delay}ms`,
    );

    clearReconnectTimeout();
    reconnectTimeoutRef.current = setTimeout(() => {
      if (!isUnmountedRef.current) {
        setReconnectAttempt((prev) => prev + 1);
      }
    }, delay);
  }, [reconnectAttempt, autoReconnect, clearReconnectTimeout]);

  const handleEvent = useCallback(
    (event: GraphDebateEvent) => {
      // Filter by debate ID if provided
      if (debateId && event.data.debate_id && event.data.debate_id !== debateId) {
        return;
      }

      // Only handle graph-related events
      const graphEventTypes: GraphEventType[] = [
        'graph_node_added',
        'graph_branch_created',
        'graph_branch_merged',
        'graph_debate_complete',
        'debate_branch',
        'debate_merge',
      ];

      if (!graphEventTypes.includes(event.type)) {
        return;
      }

      logger.debug(`Graph WebSocket event: ${event.type}`, event.data);
      setLastEvent(event);
      setEvents((prev) => [...prev.slice(-99), event]); // Keep last 100 events
    },
    [debateId],
  );

  const connect = useCallback(() => {
    if (!enabled) return;

    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    try {
      const url = wsUrl.endsWith('/') ? wsUrl.slice(0, -1) : wsUrl;
      logger.debug(`Connecting to Graph WebSocket: ${url}`);

      const ws = new WebSocket(url);
      wsRef.current = ws;
      setStatus('connecting');
      setError(null);

      ws.onopen = () => {
        logger.debug(`Graph WebSocket connected (attempt ${reconnectAttempt + 1})`);
        setStatus('connected');
        setReconnectAttempt(0); // Reset on successful connection
        hasEverConnectedRef.current = true;
        handshakeFailuresRef.current = 0;

        // Subscribe to graph events if debate ID is provided
        if (debateId) {
          ws.send(
            JSON.stringify({ type: 'subscribe', channel: 'graph_debate', debate_id: debateId }),
          );
        }
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as GraphDebateEvent;
          handleEvent(data);
        } catch (err) {
          logger.error('Failed to parse Graph WebSocket event:', err);
        }
      };

      ws.onerror = (err) => {
        logger.error('Graph WebSocket error:', err);
        // Don't set error status here - let onclose handle reconnection
      };

      ws.onclose = (event) => {
        logger.debug('Graph WebSocket closed', { code: event.code, reason: event.reason });
        wsRef.current = null;

        // Normal closure (code 1000) or page navigation (1001)
        if (event.code === 1000 || event.code === 1001) {
          setStatus('disconnected');
          return;
        }

        if (!hasEverConnectedRef.current) {
          handshakeFailuresRef.current += 1;
          if (handshakeFailuresRef.current >= MAX_HANDSHAKE_FAILURES) {
            setStatus('error');
            setError('WebSocket unavailable');
            return;
          }
        }

        // Abnormal closure - attempt reconnection
        if (!isUnmountedRef.current && autoReconnect) {
          setStatus('connecting');
          setError(`Connection lost (code: ${event.code}). Reconnecting...`);
          scheduleReconnect();
        } else {
          setStatus('error');
          setError('Connection closed');
        }
      };
    } catch (err) {
      logger.error('Failed to create Graph WebSocket:', err);
      setError(err instanceof Error ? err.message : 'Connection failed');
      setStatus('error');
      scheduleReconnect();
    }
  }, [enabled, wsUrl, debateId, autoReconnect, reconnectAttempt, handleEvent, scheduleReconnect]);

  const reconnect = useCallback(() => {
    clearReconnectTimeout();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    // Reset state
    setStatus('connecting');
    setError(null);
    setEvents([]);
    setLastEvent(null);
    setReconnectAttempt(0);
    hasEverConnectedRef.current = false;
    handshakeFailuresRef.current = 0;
    // Will trigger connection via useEffect
  }, [clearReconnectTimeout]);

  const clearEvents = useCallback(() => {
    setEvents([]);
    setLastEvent(null);
  }, []);

  // Track unmount state
  useEffect(() => {
    isUnmountedRef.current = false;
    return () => {
      isUnmountedRef.current = true;
      clearReconnectTimeout();
    };
  }, [clearReconnectTimeout]);

  // Initial connection effect
  useEffect(() => {
    if (!enabled) return;

    // Don't reconnect if max attempts reached
    if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS && status === 'error') {
      return;
    }

    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted');
        wsRef.current = null;
      }
    };
  }, [enabled, connect, reconnectAttempt, status]);

  return {
    status,
    error,
    isConnected: status === 'connected',
    reconnectAttempt,
    events,
    lastEvent,
    reconnect,
    clearEvents,
  };
}
