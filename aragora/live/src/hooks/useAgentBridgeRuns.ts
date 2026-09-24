'use client';

import { useEffect, useMemo, useState } from 'react';

import type {
  AgentBridgeRunListResponse,
  AgentBridgeRunSummary,
  BridgeApiError,
  BridgeSchemaVersion,
} from '@/components/autonomous/bridge/types';
import { useSWRFetch } from './useSWRFetch';

const PAGE_SIZE = 100;

interface LoadedBridgeRunPage {
  cursor: string | null;
  response: AgentBridgeRunListResponse;
}

export interface UseAgentBridgeRunsResult {
  schemaVersion: BridgeSchemaVersion | null;
  runs: AgentBridgeRunSummary[];
  nextCursor: string | null;
  hasMore: boolean;
  isLoading: boolean;
  isLoadingMore: boolean;
  error: BridgeApiError | null;
  errorStatus: number | null;
  loadMore: () => void;
  retry: () => void;
}

function buildRunsEndpoint(cursor: string | null): string {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (cursor) {
    params.set('cursor', cursor);
  }
  return `/api/v1/agent-bridge/runs?${params.toString()}`;
}

export function useAgentBridgeRuns(): UseAgentBridgeRunsResult {
  const [requestCursor, setRequestCursor] = useState<string | null>(null);
  const [pages, setPages] = useState<LoadedBridgeRunPage[]>([]);

  const query = useSWRFetch<AgentBridgeRunListResponse>(buildRunsEndpoint(requestCursor));

  useEffect(() => {
    const data = query.data;
    if (!data) {
      return;
    }

    setPages((previousPages) => {
      const nextPage: LoadedBridgeRunPage = { cursor: requestCursor, response: data };
      if (requestCursor === null) {
        return [nextPage];
      }

      const filteredPages = previousPages.filter((page) => page.cursor !== requestCursor);
      return [...filteredPages, nextPage];
    });
  }, [query.data, requestCursor]);

  const runs = useMemo(() => {
    const seenRunIds = new Set<string>();
    return pages
      .flatMap((page) => page.response.runs)
      .filter((run) => {
        if (seenRunIds.has(run.run_id)) {
          return false;
        }

        seenRunIds.add(run.run_id);
        return true;
      });
  }, [pages]);

  const lastPage = pages[pages.length - 1]?.response ?? null;
  const nextCursor = lastPage?.next_cursor ?? null;
  const hasMore = typeof nextCursor === 'string' && nextCursor.length > 0;
  const currentPageLoaded = pages.some((page) => page.cursor === requestCursor);
  const isLoadingMore =
    requestCursor !== null && !currentPageLoaded && (query.isLoading || query.isValidating);
  const error = query.error as BridgeApiError | null;
  const errorStatus = typeof error?.status === 'number' ? error.status : null;

  return {
    schemaVersion: lastPage?.schema_version ?? null,
    runs,
    nextCursor,
    hasMore,
    isLoading: runs.length === 0 && query.isLoading,
    isLoadingMore,
    error,
    errorStatus,
    loadMore: () => {
      if (!hasMore || !nextCursor || isLoadingMore) {
        return;
      }

      setRequestCursor(nextCursor);
    },
    retry: () => {
      void query.mutate();
    },
  };
}
