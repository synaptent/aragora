'use client';

import type { AgentBridgeRunDetail, BridgeApiError } from '@/components/autonomous/bridge/types';
import { useSWRFetch } from './useSWRFetch';

export interface UseAgentBridgeRunOptions {
  enabled?: boolean;
}

export interface UseAgentBridgeRunResult {
  run: AgentBridgeRunDetail | null;
  isLoading: boolean;
  error: BridgeApiError | null;
  errorStatus: number | null;
  retry: () => void;
}

export function useAgentBridgeRun(
  runId: string | null,
  options: UseAgentBridgeRunOptions = {},
): UseAgentBridgeRunResult {
  const { enabled = true } = options;
  const endpoint = runId ? `/api/v1/agent-bridge/runs/${encodeURIComponent(runId)}` : null;

  const query = useSWRFetch<AgentBridgeRunDetail>(endpoint, {
    enabled: enabled && Boolean(runId),
    refreshInterval: (data) => (data?.status === 'running' ? 5000 : 0),
  });

  const error = query.error as BridgeApiError | null;

  return {
    run: query.data,
    isLoading: query.isLoading,
    error,
    errorStatus: typeof error?.status === 'number' ? error.status : null,
    retry: () => {
      void query.mutate();
    },
  };
}
