'use client';

import type {
  AgentBridgeEvent,
  AgentBridgeEventsResponse,
  BridgeApiError,
} from '@/components/autonomous/bridge/types';
import { useSWRFetch } from './useSWRFetch';

const DEFAULT_EVENT_LIMIT = 500;

export interface UseAgentBridgeEventsOptions {
  enabled?: boolean;
  poll?: boolean;
  limit?: number;
}

export interface UseAgentBridgeEventsResult {
  events: AgentBridgeEvent[];
  nextCursor: string | null;
  isLoading: boolean;
  error: BridgeApiError | null;
  errorStatus: number | null;
  retry: () => void;
}

export function useAgentBridgeEvents(
  runId: string | null,
  options: UseAgentBridgeEventsOptions = {},
): UseAgentBridgeEventsResult {
  const { enabled = true, poll = false, limit = DEFAULT_EVENT_LIMIT } = options;
  const endpoint = runId
    ? `/api/v1/agent-bridge/runs/${encodeURIComponent(runId)}/events?limit=${limit}`
    : null;

  const query = useSWRFetch<AgentBridgeEventsResponse>(endpoint, {
    enabled: enabled && Boolean(runId),
    refreshInterval: poll ? 5000 : 0,
  });

  const error = query.error as BridgeApiError | null;

  return {
    events: query.data?.events ?? [],
    nextCursor: query.data?.next_cursor ?? null,
    isLoading: query.isLoading,
    error,
    errorStatus: typeof error?.status === 'number' ? error.status : null,
    retry: () => {
      void query.mutate();
    },
  };
}
