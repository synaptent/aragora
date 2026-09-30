'use client';

/**
 * Dashboard event hook — listens for global WebSocket events and triggers
 * SWR cache revalidation so the dashboard refreshes instantly when debates
 * complete, start, or update.
 *
 * When the WebSocket is connected the dashboard switches from 30 s polling
 * to event-driven refresh (with a 120 s safety-net poll). The `isConnected`
 * flag lets consumers choose the appropriate `refreshInterval`.
 */

import { useCallback, useRef, useState } from 'react';
import { useWebSocketBase } from './useWebSocketBase';
import { invalidateCachePattern } from './useSWRFetch';
import { WS_URL } from '@/config';
import { logger } from '@/utils/logger';

interface DashboardEvent {
  type: string;
  debate_id?: string;
  data?: Record<string, unknown>;
}

export interface UseDashboardEventsReturn {
  /** Whether the events WebSocket is connected */
  isConnected: boolean;
  /** Number of live updates received this session */
  updateCount: number;
}

/** Debate lifecycle events that warrant a full dashboard refresh. */
const DEBATE_REFRESH_TRIGGERS = new Set([
  'debate_end',
  'debate_complete',
  'debate_start',
  'debate_created',
  'consensus',
  'vote',
]);

/** Events that additionally affect usage / cost KPIs. */
const USAGE_REFRESH_TRIGGERS = new Set(['debate_end', 'debate_complete']);

/**
 * Subscribes to global debate lifecycle events via WebSocket and
 * invalidates the SWR cache so dashboard data refreshes immediately.
 *
 * Events handled:
 *   debate_end, debate_complete, debate_start, debate_created,
 *   consensus, vote
 */
export function useDashboardEvents(): UseDashboardEventsReturn {
  // useState so consumers re-render when the count changes
  const [updateCount, setUpdateCount] = useState(0);
  const lastInvalidationRef = useRef(0);

  const onEvent = useCallback((event: DashboardEvent) => {
    const eventType = event.type;

    if (!DEBATE_REFRESH_TRIGGERS.has(eventType)) {
      return;
    }

    // Debounce: skip if we invalidated less than 500 ms ago
    const now = Date.now();
    if (now - lastInvalidationRef.current < 500) {
      return;
    }
    lastInvalidationRef.current = now;

    logger.debug('[Dashboard] Revalidating SWR caches for event:', eventType);

    setUpdateCount((c) => c + 1);

    // Invalidate debate-related SWR caches
    invalidateCachePattern(/\/api\/v1\/debates/);
    invalidateCachePattern(/\/api\/debates/);
    invalidateCachePattern(/\/api\/health/);

    // For events that signal debate completion, also refresh usage / cost KPIs
    if (USAGE_REFRESH_TRIGGERS.has(eventType)) {
      invalidateCachePattern(/\/api\/v1\/usage\//);
      invalidateCachePattern(/\/api\/v1\/costs/);
    }
  }, []);

  const { isConnected } = useWebSocketBase<DashboardEvent>({
    wsUrl: WS_URL,
    enabled: true,
    autoReconnect: true,
    subscribeMessage: { type: 'subscribe', channel: 'dashboard' },
    onEvent,
    logPrefix: '[Dashboard]',
  });

  return { isConnected, updateCount };
}

export default useDashboardEvents;
