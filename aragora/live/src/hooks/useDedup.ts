'use client';

import { useState, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';

// Types
export interface DuplicateMatch {
  node_id: string;
  similarity: number;
  content_preview: string;
  tier: string;
  confidence: number;
}

export interface DuplicateCluster {
  cluster_id: string;
  primary_node_id: string;
  duplicate_count: number;
  avg_similarity: number;
  recommended_action: 'merge' | 'review' | 'keep_separate';
  duplicates: DuplicateMatch[];
}

export interface DedupReport {
  workspace_id: string;
  generated_at: string;
  total_nodes_analyzed: number;
  duplicate_clusters_found: number;
  estimated_reduction_percent: number;
  cluster_count: number;
}

export interface MergeResult {
  success: boolean;
  kept_node_id: string;
  merged_node_ids: string[];
  archived_count: number;
  updated_relationships: number;
}

export interface AutoMergeResult {
  workspace_id: string;
  dry_run: boolean;
  duplicates_found: number;
  merges_performed: number;
  details: string[];
}

interface UseDedupOptions {
  workspaceId?: string;
}

export function useDedup({ workspaceId = 'default' }: UseDedupOptions = {}) {
  const { config } = useBackend();
  const [clusters, setClusters] = useState<DuplicateCluster[]>([]);
  const [report, setReport] = useState<DedupReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getBaseUrl = useCallback(() => {
    return config?.api || '';
  }, [config?.api]);

  /**
   * Find duplicate clusters in the workspace
   */
  const findDuplicates = useCallback(
    async (similarityThreshold = 0.9, limit = 100): Promise<DuplicateCluster[]> => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams({
          workspace_id: workspaceId,
          similarity_threshold: similarityThreshold.toString(),
          limit: limit.toString(),
        });

        const response = await fetch(
          `${getBaseUrl()}/api/knowledge/mound/dedup/clusters?${params}`,
        );

        if (!response.ok) {
          throw new Error(`Failed to find duplicates: ${response.statusText}`);
        }

        const data = await response.json();
        setClusters(data.clusters || []);
        return data.clusters || [];
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to find duplicates';
        setError(message);
        return [];
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl],
  );

  /**
   * Generate deduplication report
   */
  const generateReport = useCallback(
    async (similarityThreshold = 0.9): Promise<DedupReport | null> => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams({
          workspace_id: workspaceId,
          similarity_threshold: similarityThreshold.toString(),
        });

        const response = await fetch(`${getBaseUrl()}/api/knowledge/mound/dedup/report?${params}`);

        if (!response.ok) {
          throw new Error(`Failed to generate report: ${response.statusText}`);
        }

        const data = await response.json();
        setReport(data);
        return data;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to generate report';
        setError(message);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl],
  );

  /**
   * Merge a duplicate cluster
   */
  const mergeCluster = useCallback(
    async (
      clusterId: string,
      primaryNodeId?: string,
      archive = true,
    ): Promise<MergeResult | null> => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(`${getBaseUrl()}/api/knowledge/mound/dedup/merge`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workspace_id: workspaceId,
            cluster_id: clusterId,
            primary_node_id: primaryNodeId,
            archive,
          }),
        });

        if (!response.ok) {
          throw new Error(`Failed to merge cluster: ${response.statusText}`);
        }

        const result = await response.json();

        // Remove merged cluster from local state
        if (result.success) {
          setClusters((prev) => prev.filter((c) => c.cluster_id !== clusterId));
        }

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to merge cluster';
        setError(message);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl],
  );

  /**
   * Auto-merge exact duplicates
   */
  const autoMerge = useCallback(
    async (dryRun = true): Promise<AutoMergeResult | null> => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(`${getBaseUrl()}/api/knowledge/mound/dedup/auto-merge`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace_id: workspaceId, dry_run: dryRun }),
        });

        if (!response.ok) {
          throw new Error(`Failed to auto-merge: ${response.statusText}`);
        }

        const result = await response.json();

        // Refresh clusters if not dry run
        if (!dryRun && result.merges_performed > 0) {
          await findDuplicates();
        }

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to auto-merge';
        setError(message);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl, findDuplicates],
  );

  /**
   * Clear state
   */
  const clearState = useCallback(() => {
    setClusters([]);
    setReport(null);
    setError(null);
  }, []);

  return {
    // State
    clusters,
    report,
    isLoading,
    error,

    // Actions
    findDuplicates,
    generateReport,
    mergeCluster,
    autoMerge,
    clearState,
  };
}
