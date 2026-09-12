'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { logger } from '@/utils/logger';
import { WS_URL } from '@/config';

const DEFAULT_WS_URL = WS_URL;

// Reconnection configuration
const MAX_RECONNECT_ATTEMPTS = 15;
const MAX_RECONNECT_DELAY_MS = 30000; // 30 seconds cap

/**
 * Validate WebSocket URL format.
 * @returns Object with valid flag and optional error message
 */
function validateWsUrl(url: string): { valid: boolean; error?: string } {
  if (!url) {
    return { valid: false, error: 'WebSocket URL is required' };
  }
  if (!url.startsWith('ws://') && !url.startsWith('wss://')) {
    return { valid: false, error: 'Invalid WebSocket URL protocol (must be ws:// or wss://)' };
  }
  try {
    new URL(url);
  } catch {
    return { valid: false, error: 'Invalid WebSocket URL format' };
  }
  return { valid: true };
}

// Gauntlet event types
export type GauntletEventType =
  | 'gauntlet_start'
  | 'gauntlet_phase'
  | 'gauntlet_agent_active'
  | 'gauntlet_attack'
  | 'gauntlet_finding'
  | 'gauntlet_probe'
  | 'gauntlet_verification'
  | 'gauntlet_risk'
  | 'gauntlet_progress'
  | 'gauntlet_verdict'
  | 'gauntlet_complete';

export interface GauntletEvent {
  type: GauntletEventType;
  data: Record<string, unknown>;
  timestamp: number;
  seq: number;
  loop_id?: string;
}

export interface GauntletFinding {
  finding_id: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  category: string;
  title: string;
  description: string;
  source: string;
}

export interface GauntletAgent {
  name: string;
  role: string;
  status: 'idle' | 'active' | 'complete';
  attackCount: number;
  probeCount: number;
}

export interface GauntletVerdict {
  verdict: 'APPROVED' | 'APPROVED_WITH_CONDITIONS' | 'NEEDS_REVIEW' | 'REJECTED';
  confidence: number;
  riskScore: number;
  robustnessScore: number;
  findings: { critical: number; high: number; medium: number; low: number; total: number };
}

export type GauntletConnectionStatus = 'connecting' | 'streaming' | 'complete' | 'error';

interface UseGauntletWebSocketOptions {
  gauntletId: string;
  wsUrl?: string;
  enabled?: boolean;
}

interface UseGauntletWebSocketReturn {
  // Connection state
  status: GauntletConnectionStatus;
  error: string | null;
  isConnected: boolean;
  reconnectAttempt: number; // Expose for UI feedback

  // Gauntlet data
  inputType: string;
  inputSummary: string;
  phase: string;
  progress: number;
  agents: Map<string, GauntletAgent>;
  findings: GauntletFinding[];
  events: GauntletEvent[];
  verdict: GauntletVerdict | null;
  elapsedSeconds: number;

  // Actions
  reconnect: () => void;
}

export function useGauntletWebSocket({
  gauntletId,
  wsUrl = DEFAULT_WS_URL,
  enabled = true,
}: UseGauntletWebSocketOptions): UseGauntletWebSocketReturn {
  const [status, setStatus] = useState<GauntletConnectionStatus>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [inputType, setInputType] = useState<string>('');
  const [inputSummary, setInputSummary] = useState<string>('');
  const [phase, setPhase] = useState<string>('init');
  const [progress, setProgress] = useState<number>(0);
  const [agents, setAgents] = useState<Map<string, GauntletAgent>>(new Map());
  const [findings, setFindings] = useState<GauntletFinding[]>([]);
  const [events, setEvents] = useState<GauntletEvent[]>([]);
  const [verdict, setVerdict] = useState<GauntletVerdict | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const startTimeRef = useRef<number | null>(null);
  const elapsedIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isUnmountedRef = useRef(false);

  // Clear any pending reconnection timeout
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
      setStatus('error');
      setError(`Connection lost. Max reconnection attempts (${MAX_RECONNECT_ATTEMPTS}) reached.`);
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, 16s (capped at 30s)
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempt), MAX_RECONNECT_DELAY_MS);
    logger.debug(
      `[Gauntlet WebSocket] Scheduling reconnect attempt ${reconnectAttempt + 1} in ${delay}ms`,
    );

    clearReconnectTimeout();
    reconnectTimeoutRef.current = setTimeout(() => {
      if (!isUnmountedRef.current) {
        setReconnectAttempt((prev) => prev + 1);
        // Reconnection will be triggered by the useEffect dependency on reconnectAttempt
      }
    }, delay);
  }, [reconnectAttempt, clearReconnectTimeout]);

  const toGauntletFinding = useCallback(
    (payload: Record<string, unknown>): GauntletFinding | null => {
      const findingId = typeof payload.finding_id === 'string' ? payload.finding_id : null;
      const severity = typeof payload.severity === 'string' ? payload.severity.toUpperCase() : null;
      const category = typeof payload.category === 'string' ? payload.category : null;
      const title = typeof payload.title === 'string' ? payload.title : null;
      const description = typeof payload.description === 'string' ? payload.description : null;
      const source = typeof payload.source === 'string' ? payload.source : null;

      if (
        !findingId ||
        !severity ||
        !category ||
        !title ||
        !description ||
        !source ||
        !['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].includes(severity)
      ) {
        return null;
      }

      return {
        finding_id: findingId,
        severity: severity as GauntletFinding['severity'],
        category,
        title,
        description,
        source,
      };
    },
    [],
  );

  const handleEvent = useCallback(
    (event: GauntletEvent) => {
      if (!event.type.startsWith('gauntlet_')) {
        return;
      }

      const eventGauntletId = event.loop_id || (event.data as { gauntlet_id?: string }).gauntlet_id;

      if (eventGauntletId && eventGauntletId !== gauntletId) {
        return;
      }

      // Add to events list
      setEvents((prev) => [...prev, event]);

      switch (event.type) {
        case 'gauntlet_start': {
          const data = event.data as {
            input_type: string;
            input_summary: string;
            agents: string[];
          };
          setInputType(data.input_type);
          setInputSummary(data.input_summary);

          // Initialize agents
          const newAgents = new Map<string, GauntletAgent>();
          data.agents.forEach((name) => {
            newAgents.set(name, {
              name,
              role: 'analyst',
              status: 'idle',
              attackCount: 0,
              probeCount: 0,
            });
          });
          setAgents(newAgents);
          break;
        }

        case 'gauntlet_phase': {
          const data = event.data as { phase: string };
          setPhase(data.phase);
          break;
        }

        case 'gauntlet_progress': {
          const data = event.data as { progress: number; elapsed_seconds: number };
          setProgress(data.progress);
          setElapsedSeconds(data.elapsed_seconds);
          break;
        }

        case 'gauntlet_agent_active': {
          const data = event.data as { agent: string; role: string };
          setAgents((prev) => {
            const updated = new Map(prev);
            const existing = updated.get(data.agent);
            if (existing) {
              updated.set(data.agent, { ...existing, role: data.role, status: 'active' });
            }
            return updated;
          });
          break;
        }

        case 'gauntlet_attack': {
          const data = event.data as { agent: string };
          setAgents((prev) => {
            const updated = new Map(prev);
            const existing = updated.get(data.agent);
            if (existing) {
              updated.set(data.agent, { ...existing, attackCount: existing.attackCount + 1 });
            }
            return updated;
          });
          break;
        }

        case 'gauntlet_probe': {
          const data = event.data as { agent: string };
          setAgents((prev) => {
            const updated = new Map(prev);
            const existing = updated.get(data.agent);
            if (existing) {
              updated.set(data.agent, { ...existing, probeCount: existing.probeCount + 1 });
            }
            return updated;
          });
          break;
        }

        case 'gauntlet_finding': {
          const data = toGauntletFinding(event.data);
          if (data) {
            setFindings((prev) => [...prev, data]);
          } else {
            logger.warn('Gauntlet finding payload malformed:', event.data);
          }
          break;
        }

        case 'gauntlet_verdict': {
          const data = event.data as {
            verdict: string;
            confidence: number;
            risk_score: number;
            robustness_score: number;
            findings: {
              critical: number;
              high: number;
              medium: number;
              low: number;
              total: number;
            };
          };
          setVerdict({
            verdict: data.verdict as GauntletVerdict['verdict'],
            confidence: data.confidence,
            riskScore: data.risk_score,
            robustnessScore: data.robustness_score,
            findings: data.findings,
          });
          break;
        }

        case 'gauntlet_complete': {
          setStatus('complete');
          // Mark all agents as complete
          setAgents((prev) => {
            const updated = new Map(prev);
            updated.forEach((agent, name) => {
              updated.set(name, { ...agent, status: 'complete' });
            });
            return updated;
          });
          // Clean up interval
          if (elapsedIntervalRef.current) {
            clearInterval(elapsedIntervalRef.current);
          }
          break;
        }
      }
    },
    [gauntletId, toGauntletFinding],
  );

  const connect = useCallback(() => {
    if (!enabled || !gauntletId) return;

    try {
      const url = wsUrl.endsWith('/') ? wsUrl.slice(0, -1) : wsUrl;

      // Validate WebSocket URL before connecting
      const validation = validateWsUrl(url);
      if (!validation.valid) {
        logger.error(`Invalid WebSocket URL: ${validation.error}`);
        setError(validation.error || 'Invalid WebSocket URL');
        setStatus('error');
        return;
      }

      logger.debug(`Connecting to Gauntlet WebSocket: ${url}`);

      const ws = new WebSocket(url);
      wsRef.current = ws;
      setStatus('connecting');
      setError(null);

      ws.onopen = () => {
        logger.debug('Gauntlet WebSocket connected');
        setStatus('streaming');
        startTimeRef.current = Date.now();

        // Start elapsed time counter
        elapsedIntervalRef.current = setInterval(() => {
          if (startTimeRef.current) {
            setElapsedSeconds((Date.now() - startTimeRef.current) / 1000);
          }
        }, 1000);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as GauntletEvent;
          handleEvent(data);
        } catch (err) {
          logger.error('Failed to parse Gauntlet event:', err);
        }
      };

      ws.onerror = (err) => {
        logger.error('Gauntlet WebSocket error:', err);
        setError('Connection error');
        // Don't set status to error here - let onclose handle reconnection
        // The error event is always followed by a close event
      };

      ws.onclose = (event) => {
        logger.debug('Gauntlet WebSocket closed', { code: event.code, reason: event.reason });
        // Clean up interval
        if (elapsedIntervalRef.current) {
          clearInterval(elapsedIntervalRef.current);
        }
        // Only attempt reconnection for abnormal closures when not complete
        if (status !== 'complete' && !isUnmountedRef.current) {
          // Code 1000 = normal closure, 1001 = going away (page navigation)
          if (event.code !== 1000 && event.code !== 1001) {
            logger.debug('Gauntlet WebSocket abnormal close, scheduling reconnect');
            setStatus('connecting');
            scheduleReconnect();
          } else {
            setStatus('error');
            setError('Connection closed');
          }
        }
      };
    } catch (err) {
      logger.error('Failed to create Gauntlet WebSocket:', err);
      setError(err instanceof Error ? err.message : 'Connection failed');
      setStatus('error');
    }
  }, [enabled, gauntletId, wsUrl, status, handleEvent, scheduleReconnect]);

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
    setFindings([]);
    setVerdict(null);
    setProgress(0);
    setPhase('init');
    setReconnectAttempt(0);
    // Reconnect
    connect();
  }, [connect, clearReconnectTimeout]);

  // Initial connection effect
  useEffect(() => {
    isUnmountedRef.current = false;
    connect();

    return () => {
      isUnmountedRef.current = true;
      clearReconnectTimeout();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (elapsedIntervalRef.current) {
        clearInterval(elapsedIntervalRef.current);
      }
    };
  }, [connect, clearReconnectTimeout]);

  // Reconnection effect - triggers when reconnectAttempt increases
  useEffect(() => {
    if (reconnectAttempt > 0 && !isUnmountedRef.current) {
      logger.debug(`[Gauntlet WebSocket] Reconnect attempt ${reconnectAttempt}`);
      // Close existing connection if any
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      connect();
    }
  }, [reconnectAttempt, connect]);

  return {
    status,
    error,
    isConnected: status === 'streaming',
    reconnectAttempt,
    inputType,
    inputSummary,
    phase,
    progress,
    agents,
    findings,
    events,
    verdict,
    elapsedSeconds,
    reconnect,
  };
}
