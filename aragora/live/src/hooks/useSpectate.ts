'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE_URL } from '@/config';

/**
 * A single spectate event from the SpectatorStream bridge.
 */
export interface SpectateEvent {
  event_type: string;
  timestamp: string;
  data: Record<string, unknown>;
  debate_id: string | null;
  pipeline_id: string | null;
  agent_name: string | null;
  round_number: number | null;
}

export interface SpectateLiveDebateSummary {
  debate_id: string;
  recent_event_count: number;
  last_event_at: string | null;
  event_types: string[];
}

export interface SpectateStatus {
  active: boolean;
  subscribers: number;
  buffer_size: number;
  bridge_state: 'inactive' | 'idle' | 'activity_unattributed' | 'live_debates_available';
  last_event_at: string | null;
  activity_age_seconds: number | null;
  recent_activity_window_seconds: number;
  recent_event_count: number;
  live_debate_count: number;
  live_debate_ids: string[];
  live_debates: SpectateLiveDebateSummary[];
  unattributed_recent_event_count: number;
}

interface UseSpectateOptions {
  /** Poll interval in milliseconds (default: 2000) */
  pollInterval?: number;
  /** Maximum number of events to fetch per poll (default: 50) */
  maxEvents?: number;
  /** Whether polling is enabled (default: true) */
  enabled?: boolean;
}

interface UseSpectateReturn {
  /** Array of spectate events, newest last */
  events: SpectateEvent[];
  /** Whether the live stream or polling fallback is currently reachable */
  connected: boolean;
  /** Whether the hook has completed its first fetch cycle */
  loaded: boolean;
  /** Bridge status (active, subscriber count, buffer size) */
  status: SpectateStatus | null;
  /** Manually trigger a refresh */
  refresh: () => Promise<void>;
}

const SPECTATE_STREAM_EVENT_TYPES = [
  'spectate',
  'debate_start',
  'debate_end',
  'round_start',
  'round_end',
  'proposal',
  'critique',
  'refine',
  'vote',
  'judge',
  'consensus',
  'convergence',
  'converged',
  'memory_recall',
  'breakpoint',
  'breakpoint_resolved',
  'system',
  'error',
] as const;

function buildSpectateParams(
  debateId?: string,
  pipelineId?: string,
  maxEvents = 50,
): URLSearchParams {
  const params = new URLSearchParams({ count: String(maxEvents) });
  if (debateId) params.set('debate_id', debateId);
  if (pipelineId) params.set('pipeline_id', pipelineId);
  return params;
}

function spectateEventKey(event: SpectateEvent): string {
  return JSON.stringify([
    event.event_type,
    event.timestamp,
    event.debate_id,
    event.pipeline_id,
    event.agent_name,
    event.round_number,
    event.data,
  ]);
}

function appendSpectateEvent(
  currentEvents: SpectateEvent[],
  nextEvent: SpectateEvent,
  maxEvents: number,
): SpectateEvent[] {
  const deduped = new Map(currentEvents.map((event) => [spectateEventKey(event), event] as const));
  deduped.set(spectateEventKey(nextEvent), nextEvent);
  return Array.from(deduped.values()).slice(-maxEvents);
}

function isSpectateEvent(value: unknown): value is SpectateEvent {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<SpectateEvent>;
  return typeof candidate.event_type === 'string' && typeof candidate.timestamp === 'string';
}

/**
 * React hook for real-time spectate events from the SpectatorStream bridge.
 *
 * Prefers the /api/v1/spectate/stream SSE endpoint for live delivery and
 * falls back to polling /api/v1/spectate/recent when streaming is unavailable.
 *
 * @example
 * ```tsx
 * function DebateViewer({ debateId }: { debateId: string }) {
 *   const { events, connected } = useSpectate({ debateId });
 *
 *   return (
 *     <div>
 *       {connected ? 'Live' : 'Disconnected'}
 *       {events.map((e, i) => (
 *         <div key={i}>{e.event_type}: {e.agent_name}</div>
 *       ))}
 *     </div>
 *   );
 * }
 * ```
 */
export function useSpectate(
  debateId?: string,
  pipelineId?: string,
  options: UseSpectateOptions = {},
): UseSpectateReturn {
  const { pollInterval = 2000, maxEvents = 50, enabled = true } = options;

  const [events, setEvents] = useState<SpectateEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [status, setStatus] = useState<SpectateStatus | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const fallbackPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const usingFallbackRef = useRef(false);

  const fetchRecent = useCallback(async () => {
    try {
      const params = buildSpectateParams(debateId, pipelineId, maxEvents);
      const res = await fetch(`${API_BASE_URL}/api/v1/spectate/recent?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setEvents(data.events || []);
        return true;
      } else {
        setEvents([]);
        return false;
      }
    } catch {
      setEvents([]);
      return false;
    }
  }, [debateId, pipelineId, maxEvents]);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/spectate/status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
        return true;
      }
    } catch {
      // Status fetch is best-effort
    }

    setStatus(null);
    return false;
  }, []);

  const refresh = useCallback(async () => {
    const [recentOk] = await Promise.all([fetchRecent(), fetchStatus()]);
    setConnected(recentOk);
    setLoaded(true);
  }, [fetchRecent, fetchStatus]);

  const stopFallbackPolling = useCallback(() => {
    if (fallbackPollRef.current) {
      clearInterval(fallbackPollRef.current);
      fallbackPollRef.current = null;
    }
    usingFallbackRef.current = false;
  }, []);

  const startFallbackPolling = useCallback(() => {
    stopFallbackPolling();
    usingFallbackRef.current = true;
    void refresh();
    fallbackPollRef.current = setInterval(() => {
      void refresh();
    }, pollInterval);
  }, [pollInterval, refresh, stopFallbackPolling]);

  const closeEventSource = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const connectEventSource = useCallback(() => {
    if (typeof EventSource === 'undefined') {
      startFallbackPolling();
      return;
    }

    const params = buildSpectateParams(debateId, pipelineId, maxEvents);
    const source = new EventSource(`${API_BASE_URL}/api/v1/spectate/stream?${params.toString()}`);
    eventSourceRef.current = source;

    const handleConnected = () => {
      if (eventSourceRef.current !== source) return;
      setConnected(true);
      setLoaded(true);
      stopFallbackPolling();
    };

    const handleSpectateMessage = (event: MessageEvent<string>) => {
      if (eventSourceRef.current !== source) return;

      try {
        const parsed = JSON.parse(event.data) as unknown;
        if (!isSpectateEvent(parsed)) return;

        setEvents((currentEvents) => appendSpectateEvent(currentEvents, parsed, maxEvents));
        setConnected(true);
        setLoaded(true);
      } catch {
        // Ignore malformed frames and keep the stream alive.
      }
    };

    const handleResyncRequired = () => {
      if (eventSourceRef.current !== source) return;
      setConnected(false);
      closeEventSource();
      startFallbackPolling();
    };

    source.onopen = handleConnected;
    source.addEventListener('connected', handleConnected as EventListener);
    source.addEventListener('snapshot_complete', handleConnected as EventListener);
    SPECTATE_STREAM_EVENT_TYPES.forEach((eventType) => {
      source.addEventListener(eventType, handleSpectateMessage as EventListener);
    });
    source.addEventListener('resync_required', handleResyncRequired as EventListener);
    source.onerror = () => {
      if (eventSourceRef.current !== source) return;
      setConnected(false);
      closeEventSource();
      startFallbackPolling();
    };
  }, [
    closeEventSource,
    debateId,
    maxEvents,
    pipelineId,
    startFallbackPolling,
    stopFallbackPolling,
  ]);

  useEffect(() => {
    if (!enabled) {
      stopFallbackPolling();
      closeEventSource();
      if (statusPollRef.current) {
        clearInterval(statusPollRef.current);
        statusPollRef.current = null;
      }
      return;
    }

    setEvents([]);
    setConnected(false);
    setLoaded(false);

    void fetchStatus();
    statusPollRef.current = setInterval(() => {
      void fetchStatus();
    }, pollInterval);
    connectEventSource();

    return () => {
      stopFallbackPolling();
      closeEventSource();
      if (statusPollRef.current) {
        clearInterval(statusPollRef.current);
        statusPollRef.current = null;
      }
    };
  }, [
    closeEventSource,
    connectEventSource,
    enabled,
    fetchStatus,
    pollInterval,
    stopFallbackPolling,
  ]);

  const manualRefresh = useCallback(async () => {
    if (usingFallbackRef.current) {
      await refresh();
      return;
    }

    await fetchStatus();
    setLoaded(true);
  }, [fetchStatus, refresh]);

  return { events, connected, loaded, status, refresh: manualRefresh };
}
