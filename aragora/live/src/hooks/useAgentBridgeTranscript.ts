'use client';

import type {
  AgentBridgeTranscriptResponse,
  AgentBridgeTurnRecord,
  BridgeApiError,
} from '@/components/autonomous/bridge/types';
import { useSWRFetch } from './useSWRFetch';

export interface UseAgentBridgeTranscriptOptions {
  enabled?: boolean;
  poll?: boolean;
}

export interface UseAgentBridgeTranscriptResult {
  turns: AgentBridgeTurnRecord[];
  isLoading: boolean;
  error: BridgeApiError | null;
  errorStatus: number | null;
  retry: () => void;
}

export function useAgentBridgeTranscript(
  runId: string | null,
  options: UseAgentBridgeTranscriptOptions = {},
): UseAgentBridgeTranscriptResult {
  const { enabled = true, poll = false } = options;
  const endpoint = runId
    ? `/api/v1/agent-bridge/runs/${encodeURIComponent(runId)}/transcript`
    : null;

  const query = useSWRFetch<AgentBridgeTranscriptResponse>(endpoint, {
    enabled: enabled && Boolean(runId),
    refreshInterval: poll ? 5000 : 0,
  });

  const error = query.error as BridgeApiError | null;

  return {
    turns: query.data?.turns ?? [],
    isLoading: query.isLoading,
    error,
    errorStatus: typeof error?.status === 'number' ? error.status : null,
    retry: () => {
      void query.mutate();
    },
  };
}
