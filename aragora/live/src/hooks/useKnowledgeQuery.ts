'use client';

/**
 * Knowledge Query hook for interacting with the Knowledge Mound.
 *
 * Provides:
 * - Semantic search queries
 * - Node CRUD operations
 * - Graph traversal
 * - Relationship management
 * - Statistics fetching
 */

import { useCallback, useEffect, useRef } from 'react';
import { useApi } from './useApi';
import { useBackend } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';
import {
  useKnowledgeExplorerStore,
  type KnowledgeNode,
  type KnowledgeRelationship,
  type GraphNode,
  type GraphEdge,
  type NodeFilters,
  type MoundStats,
} from '@/store/knowledgeExplorerStore';

const KNOWLEDGE_API_PREFIX = '/api/v1/knowledge/mound';

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function normalizeNodeArray(payload: unknown): KnowledgeNode[] {
  if (!isRecord(payload)) {
    return [];
  }

  const candidates = Array.isArray(payload.nodes)
    ? payload.nodes
    : Array.isArray(payload.results)
      ? payload.results.map((result) => {
          if (isRecord(result) && isRecord(result.node)) {
            return result.node;
          }
          return result;
        })
      : [];

  return candidates.filter(
    (candidate): candidate is KnowledgeNode =>
      isRecord(candidate) &&
      typeof candidate.id === 'string' &&
      typeof candidate.content === 'string',
  );
}

function normalizeCount(payload: unknown, fallback: number): number {
  if (!isRecord(payload)) {
    return fallback;
  }

  const rawCount = payload.total ?? payload.total_count ?? payload.count;
  return typeof rawCount === 'number' ? rawCount : fallback;
}

function normalizeRelationships(payload: unknown): KnowledgeRelationship[] {
  const candidates = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.relationships)
      ? payload.relationships
      : [];

  return candidates.filter(
    (candidate): candidate is KnowledgeRelationship =>
      isRecord(candidate) &&
      typeof candidate.id === 'string' &&
      typeof candidate.strength === 'number',
  );
}

export interface QueryOptions {
  /** Workspace ID (default: 'default') */
  workspaceId?: string;
  /** Maximum results (default: 20) */
  limit?: number;
  /** Node types to include */
  nodeTypes?: string[];
  /** Minimum confidence score (0-1) */
  minConfidence?: number;
}

export interface UseKnowledgeQueryOptions {
  /** Auto-load statistics on mount */
  autoLoadStats?: boolean;
  /** Debounce delay for search (ms) */
  searchDebounce?: number;
}

export interface UseKnowledgeQueryReturn {
  // Query state
  queryText: string;
  isQueryExecuting: boolean;
  queryResults: KnowledgeNode[];
  queryError: string | null;

  // Browser state
  browserNodes: KnowledgeNode[];
  browserLoading: boolean;
  browserError: string | null;
  totalNodes: number;

  // Graph state
  graphNodes: GraphNode[];
  graphEdges: GraphEdge[];
  graphLoading: boolean;
  graphError: string | null;

  // Statistics
  stats: MoundStats | null;
  statsLoading: boolean;

  // Query operations
  setQueryText: (text: string) => void;
  executeQuery: (text?: string, options?: QueryOptions) => Promise<KnowledgeNode[]>;
  clearQueryResults: () => void;

  // Node operations
  loadNodes: (filters?: Partial<NodeFilters>) => Promise<void>;
  getNode: (id: string) => Promise<KnowledgeNode>;
  createNode: (node: Partial<KnowledgeNode>) => Promise<string>;
  updateNode: (id: string, updates: Partial<KnowledgeNode>) => Promise<void>;
  deleteNode: (id: string) => Promise<void>;

  // Graph operations
  loadGraph: (
    nodeId: string,
    depth?: number,
    direction?: 'outgoing' | 'incoming' | 'both',
  ) => Promise<void>;
  clearGraph: () => void;

  // Relationship operations
  createRelationship: (
    fromId: string,
    toId: string,
    type: string,
    strength?: number,
  ) => Promise<string>;
  deleteRelationship: (id: string) => Promise<void>;
  getNodeRelationships: (nodeId: string) => Promise<KnowledgeRelationship[]>;

  // Statistics
  loadStats: () => Promise<void>;
}

/**
 * Hook for Knowledge Mound interactions.
 *
 * @example
 * ```tsx
 * const {
 *   queryText,
 *   setQueryText,
 *   executeQuery,
 *   queryResults,
 *   loadGraph,
 *   graphNodes,
 *   graphEdges,
 * } = useKnowledgeQuery({
 *   autoLoadStats: true,
 * });
 *
 * // Search for knowledge
 * const results = await executeQuery('contract risk factors');
 *
 * // Load graph from a node
 * await loadGraph('node_123', 3, 'both');
 * ```
 */
export function useKnowledgeQuery({
  autoLoadStats = true,
  searchDebounce: _searchDebounce = 300,
}: UseKnowledgeQueryOptions = {}): UseKnowledgeQueryReturn {
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // Get store state and actions
  const store = useKnowledgeExplorerStore();
  const {
    query,
    browser,
    graph,
    stats,
    statsLoading,
    setQueryText: setStoreQueryText,
    setQueryExecuting,
    setQueryResults,
    setQueryError,
    clearQueryResults: clearStoreQueryResults,
    setBrowserNodes,
    setBrowserLoading,
    setBrowserError,
    setGraphData,
    setGraphLoading,
    setGraphError,
    clearGraph: clearStoreGraph,
    setStats,
    setStatsLoading,
  } = store;

  // Debounce ref for search
  const searchTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Load stats on mount if enabled
  useEffect(() => {
    if (autoLoadStats) {
      loadStats();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadStats is defined later, mount-only
  }, [autoLoadStats]);

  // Set query text with optional debounced execution
  const setQueryText = useCallback(
    (text: string) => {
      setStoreQueryText(text);

      // Clear existing timer
      if (searchTimerRef.current) {
        clearTimeout(searchTimerRef.current);
      }
    },
    [setStoreQueryText],
  );

  // Execute semantic query
  const executeQuery = useCallback(
    async (text?: string, options?: QueryOptions): Promise<KnowledgeNode[]> => {
      const queryString = text ?? query.text;
      if (!queryString.trim()) {
        return [];
      }

      setQueryExecuting(true);
      setQueryError(null);

      try {
        const response = (await api.post(`${KNOWLEDGE_API_PREFIX}/query`, {
          query: queryString,
          workspace_id: options?.workspaceId || 'default',
          limit: options?.limit || 20,
          node_types: options?.nodeTypes,
          min_confidence: options?.minConfidence || 0,
        })) as unknown;

        const nodes = normalizeNodeArray(response);
        setQueryResults(nodes, normalizeCount(response, nodes.length));
        return nodes;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Query failed';
        clearStoreQueryResults();
        setQueryError(message);
        return [];
      }
    },
    [api, clearStoreQueryResults, query.text, setQueryExecuting, setQueryResults, setQueryError],
  );

  // Clear query results
  const clearQueryResults = useCallback(() => {
    clearStoreQueryResults();
  }, [clearStoreQueryResults]);

  // Load nodes with filters
  const loadNodes = useCallback(
    async (filters?: Partial<NodeFilters>): Promise<void> => {
      setBrowserLoading(true);
      setBrowserError(null);

      try {
        const params = new URLSearchParams();
        if (filters?.workspace) params.append('workspace_id', filters.workspace);
        if (filters?.nodeTypes?.length) params.append('node_types', filters.nodeTypes.join(','));
        if (filters?.minConfidence) params.append('min_confidence', String(filters.minConfidence));
        if (filters?.tier) params.append('tier', filters.tier);
        if (filters?.topics?.length) params.append('topics', filters.topics.join(','));

        const response = (await api.get(
          `${KNOWLEDGE_API_PREFIX}/nodes${params.size > 0 ? `?${params.toString()}` : ''}`,
        )) as unknown;

        const nodes = normalizeNodeArray(response);
        setBrowserNodes(nodes, normalizeCount(response, nodes.length));
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to load nodes';
        setBrowserNodes([], 0);
        setBrowserError(message);
      }
    },
    [api, setBrowserNodes, setBrowserLoading, setBrowserError],
  );

  // Get a single node
  const getNode = useCallback(
    async (id: string): Promise<KnowledgeNode> => {
      const response = (await api.get(`${KNOWLEDGE_API_PREFIX}/nodes/${id}`)) as KnowledgeNode;
      return response;
    },
    [api],
  );

  // Create a new node
  const createNode = useCallback(
    async (node: Partial<KnowledgeNode>): Promise<string> => {
      const response = (await api.post(`${KNOWLEDGE_API_PREFIX}/nodes`, {
        node_type: node.node_type || 'fact',
        content: node.content,
        confidence: node.confidence || 0.5,
        tier: node.tier || 'slow',
        workspace_id: node.workspace_id || 'default',
        topics: node.topics || [],
        metadata: node.metadata || {},
      })) as { id: string };

      return response.id;
    },
    [api],
  );

  // Update a node
  const updateNode = useCallback(
    async (id: string, updates: Partial<KnowledgeNode>): Promise<void> => {
      await api.put(`${KNOWLEDGE_API_PREFIX}/nodes/${id}`, updates);
    },
    [api],
  );

  // Delete a node
  const deleteNode = useCallback(
    async (id: string): Promise<void> => {
      await api.delete(`${KNOWLEDGE_API_PREFIX}/nodes/${id}`);
    },
    [api],
  );

  // Load graph from a node
  const loadGraph = useCallback(
    async (
      nodeId: string,
      depth: number = 2,
      direction: 'outgoing' | 'incoming' | 'both' = 'both',
    ): Promise<void> => {
      setGraphLoading(true);
      setGraphError(null);

      try {
        const response = (await api.get(
          `${KNOWLEDGE_API_PREFIX}/graph/${nodeId}?depth=${depth}&direction=${direction}`,
        )) as { nodes: GraphNode[]; edges: GraphEdge[] };

        // Process nodes to ensure they have position data for D3
        const processedNodes = (response.nodes || []).map((node) => ({
          ...node,
          // Initial positions will be set by D3 force simulation
          x: node.x ?? 0,
          y: node.y ?? 0,
          depth: node.depth ?? 0,
        }));

        setGraphData(processedNodes, response.edges || []);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to load graph';
        setGraphError(message);
      }
    },
    [api, setGraphData, setGraphLoading, setGraphError],
  );

  // Clear graph
  const clearGraph = useCallback(() => {
    clearStoreGraph();
  }, [clearStoreGraph]);

  // Create a relationship
  const createRelationship = useCallback(
    async (fromId: string, toId: string, type: string, strength: number = 0.5): Promise<string> => {
      const response = (await api.post(`${KNOWLEDGE_API_PREFIX}/relationships`, {
        from_node_id: fromId,
        to_node_id: toId,
        relationship_type: type,
        strength,
      })) as { id: string };

      return response.id;
    },
    [api],
  );

  // Delete a relationship
  const deleteRelationship = useCallback(
    async (id: string): Promise<void> => {
      await api.delete(`${KNOWLEDGE_API_PREFIX}/relationships/${id}`);
    },
    [api],
  );

  // Get relationships for a node
  const getNodeRelationships = useCallback(
    async (nodeId: string): Promise<KnowledgeRelationship[]> => {
      const response = (await api.get(
        `${KNOWLEDGE_API_PREFIX}/nodes/${nodeId}/relationships`,
      )) as unknown;
      return normalizeRelationships(response);
    },
    [api],
  );

  // Load statistics
  const loadStats = useCallback(async (): Promise<void> => {
    setStatsLoading(true);

    try {
      const response = (await api.get(`${KNOWLEDGE_API_PREFIX}/stats`)) as MoundStats;
      setStats(response);
    } catch (error) {
      logger.error('Failed to load knowledge mound stats:', error);
      setStats(null);
    }
  }, [api, setStats, setStatsLoading]);

  return {
    // Query state
    queryText: query.text,
    isQueryExecuting: query.isExecuting,
    queryResults: query.results,
    queryError: query.error,

    // Browser state
    browserNodes: browser.nodes,
    browserLoading: browser.isLoading,
    browserError: browser.error,
    totalNodes: browser.totalNodes,

    // Graph state
    graphNodes: graph.nodes,
    graphEdges: graph.edges,
    graphLoading: graph.isLoading,
    graphError: graph.error,

    // Statistics
    stats,
    statsLoading,

    // Operations
    setQueryText,
    executeQuery,
    clearQueryResults,
    loadNodes,
    getNode,
    createNode,
    updateNode,
    deleteNode,
    loadGraph,
    clearGraph,
    createRelationship,
    deleteRelationship,
    getNodeRelationships,
    loadStats,
  };
}

export default useKnowledgeQuery;
