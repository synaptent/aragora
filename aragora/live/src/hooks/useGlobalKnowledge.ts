'use client';

/**
 * Global Knowledge hook for accessing system-wide verified facts.
 *
 * Provides:
 * - Query global knowledge
 * - Store verified facts (admin)
 * - Promote workspace knowledge to global (admin)
 */

import { useState, useCallback } from 'react';
import { useApi } from './useApi';
import { useBackend } from '@/components/BackendSelector';
import type { KnowledgeNode } from '@/store/knowledgeExplorerStore';

export interface StoreFactRequest {
  content: string;
  source: string;
  confidence: number;
  evidenceIds?: string[];
}

export interface PromoteRequest {
  itemId: string;
  workspaceId: string;
  reason: string;
}

export interface UseGlobalKnowledgeOptions {
  /** Whether current user is admin */
  isAdmin?: boolean;
}

export interface UseGlobalKnowledgeReturn {
  // State
  results: KnowledgeNode[];
  isLoading: boolean;
  error: string | null;

  // Query operations
  queryGlobal: (query: string, limit?: number) => Promise<KnowledgeNode[]>;

  // Admin operations (require isAdmin)
  storeFact: (request: StoreFactRequest) => Promise<string>;
  promoteToGlobal: (request: PromoteRequest) => Promise<string>;
}

export function useGlobalKnowledge(
  options: UseGlobalKnowledgeOptions = {},
): UseGlobalKnowledgeReturn {
  const { isAdmin = false } = options;
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);
  const [results, setResults] = useState<KnowledgeNode[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const queryGlobal = useCallback(
    async (query: string, limit = 20): Promise<KnowledgeNode[]> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.post('/api/knowledge/mound/global/query', {
          query,
          limit,
        })) as { results: KnowledgeNode[] };
        setResults(response.results);
        return response.results;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to query global knowledge';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api],
  );

  const storeFact = useCallback(
    async (storeRequest: StoreFactRequest): Promise<string> => {
      if (!isAdmin) {
        throw new Error('Admin access required to store verified facts');
      }

      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.post('/api/knowledge/mound/global/facts', {
          content: storeRequest.content,
          source: storeRequest.source,
          confidence: storeRequest.confidence,
          evidence_ids: storeRequest.evidenceIds,
        })) as { fact_id: string };
        return response.fact_id;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to store fact';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, isAdmin],
  );

  const promoteToGlobal = useCallback(
    async (promoteRequest: PromoteRequest): Promise<string> => {
      if (!isAdmin) {
        throw new Error('Admin access required to promote to global');
      }

      setIsLoading(true);
      setError(null);
      try {
        const response = (await api.post('/api/knowledge/mound/global/promote', {
          item_id: promoteRequest.itemId,
          workspace_id: promoteRequest.workspaceId,
          reason: promoteRequest.reason,
        })) as { global_id: string };
        return response.global_id;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to promote to global';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [api, isAdmin],
  );

  return { results, isLoading, error, queryGlobal, storeFact, promoteToGlobal };
}

export default useGlobalKnowledge;
