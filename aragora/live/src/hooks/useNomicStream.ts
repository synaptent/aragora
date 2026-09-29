'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import type { StreamEvent, NomicState, LoopInstance } from '@/types/events';
import { logger } from '@/utils/logger';
import { WS_URL, API_BASE_URL } from '@/config';

const DEFAULT_WS_URL = WS_URL;
const MAX_EVENTS = 5000;
const TOKENS_KEY = 'aragora_tokens';

// Circuit breaker configuration
const MAX_RECONNECT_ATTEMPTS = 15;
const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;

function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(TOKENS_KEY);
  if (!stored) return null;
  try {
    const parsed = JSON.parse(stored) as { access_token?: string };
    return parsed.access_token || null;
  } catch {
    return null;
  }
}

function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const token = getAccessToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export function useNomicStream(wsUrl: string = DEFAULT_WS_URL) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [nomicState, setNomicState] = useState<NomicState | null>(null);
  const [activeLoops, setActiveLoops] = useState<LoopInstance[]>([]);
  const [selectedLoopId, setSelectedLoopId] = useState<string | null>(null);
  const selectedLoopIdRef = useRef<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Circuit breaker state
  const reconnectAttemptsRef = useRef(0);
  const [circuitOpen, setCircuitOpen] = useState(false);

  // Audience participation callbacks
  const ackCallbacksRef = useRef<((msgType: string) => void)[]>([]);
  const errorCallbacksRef = useRef<((message: string) => void)[]>([]);

  // Ref for updateStateFromEvent to avoid stale closure in connect
  const updateStateFromEventRef = useRef<(event: StreamEvent) => void>(() => {});

  const connect = useCallback(() => {
    // Skip connection when no URL provided (e.g. unauthenticated users)
    if (!wsUrl) return;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        // Reset circuit breaker on successful connection
        reconnectAttemptsRef.current = 0;
        setCircuitOpen(false);
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;

        // Circuit breaker: stop reconnecting after MAX_RECONNECT_ATTEMPTS
        if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
          setCircuitOpen(true);
          return;
        }

        // Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s (max)
        const backoffMs = Math.min(
          INITIAL_BACKOFF_MS * Math.pow(2, reconnectAttemptsRef.current),
          MAX_BACKOFF_MS,
        );
        reconnectAttemptsRef.current += 1;

        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, backoffMs);
      };

      ws.onerror = (error) => {
        logger.error('WebSocket error:', error);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as StreamEvent;

          // Handle sync event (initial state)
          if (data.type === 'sync') {
            setNomicState(data.data as NomicState);
            return;
          }

          // Handle loop list event (sent on connect and on request)
          if (data.type === 'loop_list') {
            const loopData = data.data as { loops: LoopInstance[]; count: number };
            setActiveLoops(loopData.loops || []);
            // Find the loop to use for state (use ref to avoid stale closure)
            const currentLoopId = selectedLoopIdRef.current;
            const targetLoop = currentLoopId
              ? loopData.loops?.find((l) => l.loop_id === currentLoopId)
              : loopData.loops?.[0];
            if (targetLoop) {
              if (!currentLoopId) {
                setSelectedLoopId(targetLoop.loop_id);
                selectedLoopIdRef.current = targetLoop.loop_id;
              }
              // Initialize/update nomicState from loop data
              setNomicState((prev) => ({
                ...prev,
                cycle: targetLoop.cycle || 0,
                phase: targetLoop.phase || 'starting',
              }));
            }
            return;
          }

          // Handle loop registration
          if (data.type === 'loop_register') {
            const newLoop: LoopInstance = {
              loop_id: data.data.loop_id as string,
              name: data.data.name as string,
              started_at: data.data.started_at as number,
              cycle: 0,
              phase: 'starting',
              path: data.data.path as string,
            };
            setActiveLoops((prev) => [...prev, newLoop]);
            // Auto-select if this is the first loop
            if (!selectedLoopIdRef.current) {
              setSelectedLoopId(newLoop.loop_id);
              selectedLoopIdRef.current = newLoop.loop_id;
            }
            return;
          }

          // Handle loop unregistration
          if (data.type === 'loop_unregister') {
            const loopId = data.data.loop_id as string;
            setActiveLoops((prev) => prev.filter((l) => l.loop_id !== loopId));
            // Selection update handled by useEffect below
            return;
          }

          // Handle audience participation acknowledgments
          if (data.type === 'ack') {
            const msgType = data.data.msg_type as string;
            ackCallbacksRef.current.forEach((cb) => cb(msgType));
            return;
          }

          // Handle audience participation errors
          if (data.type === 'error') {
            const message = data.data.message as string;
            errorCallbacksRef.current.forEach((cb) => cb(message));
            return;
          }

          // Add event to list, keeping only last MAX_EVENTS
          setEvents((prev) => {
            const newEvents = [...prev, data];
            if (newEvents.length > MAX_EVENTS) {
              return newEvents.slice(-MAX_EVENTS);
            }
            return newEvents;
          });

          // Update state based on event type
          updateStateFromEventRef.current(data);
        } catch (e) {
          logger.error('Failed to parse WebSocket message:', e);
        }
      };
    } catch (e) {
      logger.error('Failed to create WebSocket:', e);

      // Circuit breaker check
      if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
        setCircuitOpen(true);
        return;
      }

      // Exponential backoff for connection errors
      const backoffMs = Math.min(
        INITIAL_BACKOFF_MS * Math.pow(2, reconnectAttemptsRef.current),
        MAX_BACKOFF_MS,
      );
      reconnectAttemptsRef.current += 1;

      reconnectTimeoutRef.current = setTimeout(connect, backoffMs);
    }
  }, [wsUrl]);

  const updateStateFromEvent = useCallback((event: StreamEvent) => {
    switch (event.type) {
      case 'cycle_start':
        setNomicState((prev) => ({
          ...prev,
          phase: 'starting',
          cycle: event.data.cycle as number,
        }));
        break;
      case 'phase_start':
        setNomicState((prev) => ({ ...prev, phase: event.data.phase as string, stage: 'running' }));
        break;
      case 'phase_end':
        setNomicState((prev) => ({ ...prev, stage: event.data.success ? 'complete' : 'failed' }));
        break;
      case 'task_complete':
        setNomicState((prev) => ({
          ...prev,
          completed_tasks: (prev?.completed_tasks || 0) + 1,
          last_task: event.data.task_id as string,
          last_success: event.data.success as boolean,
        }));
        break;
      case 'cycle_end':
        setNomicState((prev) => ({
          ...prev,
          phase: 'complete',
          stage: event.data.outcome as string,
        }));
        break;
    }
  }, []);

  // Keep ref in sync with callback
  useEffect(() => {
    updateStateFromEventRef.current = updateStateFromEvent;
  }, [updateStateFromEvent]);

  // Sync selectedLoopId when selected loop is removed (fixes race condition)
  useEffect(() => {
    if (selectedLoopId && !activeLoops.find((l) => l.loop_id === selectedLoopId)) {
      // Selected loop no longer exists, select first available or null
      const newId = activeLoops.length > 0 ? activeLoops[0].loop_id : null;
      setSelectedLoopId(newId);
      selectedLoopIdRef.current = newId;
    }
  }, [activeLoops, selectedLoopId]);

  useEffect(() => {
    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect]);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  // Reset circuit breaker and attempt to reconnect
  const resetCircuitBreaker = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    setCircuitOpen(false);
    connect();
  }, [connect]);

  const selectLoop = useCallback((loopId: string) => {
    setSelectedLoopId(loopId);
    selectedLoopIdRef.current = loopId;
    // Clear events when switching loops (optional - remove if you want to keep history)
    setEvents([]);
  }, []);

  const requestLoopList = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'get_loops' }));
    }
  }, []);

  const sendMessage = useCallback((message: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      // Auto-inject loop_id for audience participation messages
      const messageType = message.type as string;
      if (
        (messageType === 'user_vote' || messageType === 'user_suggestion') &&
        !message.loop_id &&
        selectedLoopIdRef.current
      ) {
        message = { ...message, loop_id: selectedLoopIdRef.current };
      }
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  const onAck = useCallback((callback: (msgType: string) => void) => {
    ackCallbacksRef.current.push(callback);
    return () => {
      ackCallbacksRef.current = ackCallbacksRef.current.filter((cb) => cb !== callback);
    };
  }, []);

  const onError = useCallback((callback: (message: string) => void) => {
    errorCallbacksRef.current.push(callback);
    return () => {
      errorCallbacksRef.current = errorCallbacksRef.current.filter((cb) => cb !== callback);
    };
  }, []);

  const forkReplay = useCallback(
    async (debateId: string, eventId: string, configOverrides: object = {}) => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/replays/${debateId}/fork`, {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ event_id: eventId, config: configOverrides }),
        });
        if (!response.ok) {
          throw new Error(`Fork failed: ${response.status}`);
        }
        const forkData = await response.json();
        return forkData;
      } catch (error) {
        logger.error('Fork error:', error);
        throw error;
      }
    },
    [],
  );

  return {
    events,
    connected,
    nomicState,
    clearEvents,
    // Multi-loop support
    activeLoops,
    selectedLoopId,
    selectLoop,
    requestLoopList,
    sendMessage,
    // Audience participation
    onAck,
    onError,
    // Replay forking
    forkReplay,
    // Circuit breaker
    circuitOpen,
    resetCircuitBreaker,
  };
}

// Fetch nomic state from REST API
export async function fetchNomicState(apiUrl: string = API_BASE_URL): Promise<NomicState> {
  const response = await fetch(`${apiUrl}/api/nomic/state`, { headers: getAuthHeaders() });
  if (!response.ok) {
    throw new Error(`Failed to fetch state: ${response.status}`);
  }
  return response.json();
}

// Fetch nomic log lines from REST API
export async function fetchNomicLog(
  apiUrl: string = API_BASE_URL,
  lines: number = 100,
): Promise<string[]> {
  const response = await fetch(`${apiUrl}/api/nomic/log?lines=${lines}`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch log: ${response.status}`);
  }
  const data = await response.json();
  return data.lines || [];
}
