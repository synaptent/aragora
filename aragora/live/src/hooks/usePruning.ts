'use client';

import { useState, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';

// Types
export type PruningAction = 'archive' | 'delete' | 'demote' | 'flag';

export interface PrunableItem {
  node_id: string;
  content_preview: string;
  staleness_score: number;
  confidence: number;
  retrieval_count: number;
  last_retrieved_at: string | null;
  tier: string;
  created_at: string;
  prune_reason: string;
  recommended_action: PruningAction;
}

export interface PruneResult {
  success: boolean;
  workspace_id: string;
  executed_at: string;
  items_analyzed: number;
  items_pruned: number;
  items_archived: number;
  items_deleted: number;
  items_demoted: number;
  items_flagged: number;
  pruned_item_ids: string[];
  errors: string[];
}

export interface PruneHistoryEntry {
  history_id: string;
  executed_at: string;
  policy_id: string;
  action: PruningAction;
  items_pruned: number;
  pruned_item_ids: string[];
  reason: string;
  executed_by: string;
}

interface UsePruningOptions {
  workspaceId?: string;
}

export function usePruning({ workspaceId = 'default' }: UsePruningOptions = {}) {
  const { config } = useBackend();
  const [prunableItems, setPrunableItems] = useState<PrunableItem[]>([]);
  const [history, setHistory] = useState<PruneHistoryEntry[]>([]);
  const [lastResult, setLastResult] = useState<PruneResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getBaseUrl = useCallback(() => {
    return config?.api || '';
  }, [config?.api]);

  /**
   * Get items eligible for pruning
   */
  const getPrunableItems = useCallback(
    async (stalenessThreshold = 0.9, minAgeDays = 30, limit = 100): Promise<PrunableItem[]> => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams({
          workspace_id: workspaceId,
          staleness_threshold: stalenessThreshold.toString(),
          min_age_days: minAgeDays.toString(),
          limit: limit.toString(),
        });

        const response = await fetch(`${getBaseUrl()}/api/knowledge/mound/pruning/items?${params}`);

        if (!response.ok) {
          throw new Error(`Failed to get prunable items: ${response.statusText}`);
        }

        const data = await response.json();
        setPrunableItems(data.items || []);
        return data.items || [];
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to get prunable items';
        setError(message);
        return [];
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl],
  );

  /**
   * Execute pruning on specified items
   */
  const pruneItems = useCallback(
    async (
      itemIds: string[],
      action: PruningAction = 'archive',
      reason = 'manual_prune',
    ): Promise<PruneResult | null> => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(`${getBaseUrl()}/api/knowledge/mound/pruning/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace_id: workspaceId, item_ids: itemIds, action, reason }),
        });

        if (!response.ok) {
          throw new Error(`Failed to prune items: ${response.statusText}`);
        }

        const result = await response.json();
        setLastResult(result);

        // Remove pruned items from local state
        if (result.success) {
          setPrunableItems((prev) =>
            prev.filter((item) => !result.pruned_item_ids.includes(item.node_id)),
          );
        }

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to prune items';
        setError(message);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl],
  );

  /**
   * Run auto-prune with policy
   */
  const autoPrune = useCallback(
    async (
      options: {
        stalenessThreshold?: number;
        minAgeDays?: number;
        action?: PruningAction;
        dryRun?: boolean;
      } = {},
    ): Promise<PruneResult | null> => {
      setIsLoading(true);
      setError(null);

      const {
        stalenessThreshold = 0.9,
        minAgeDays = 30,
        action = 'archive',
        dryRun = true,
      } = options;

      try {
        const response = await fetch(`${getBaseUrl()}/api/knowledge/mound/pruning/auto`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workspace_id: workspaceId,
            staleness_threshold: stalenessThreshold,
            min_age_days: minAgeDays,
            action,
            dry_run: dryRun,
          }),
        });

        if (!response.ok) {
          throw new Error(`Failed to auto-prune: ${response.statusText}`);
        }

        const result = await response.json();
        setLastResult(result);

        // Refresh prunable items if not dry run
        if (!dryRun && result.items_pruned > 0) {
          await getPrunableItems(stalenessThreshold, minAgeDays);
        }

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to auto-prune';
        setError(message);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl, getPrunableItems],
  );

  /**
   * Get pruning history
   */
  const getHistory = useCallback(
    async (limit = 50, since?: string): Promise<PruneHistoryEntry[]> => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams({ workspace_id: workspaceId, limit: limit.toString() });
        if (since) {
          params.append('since', since);
        }

        const response = await fetch(
          `${getBaseUrl()}/api/knowledge/mound/pruning/history?${params}`,
        );

        if (!response.ok) {
          throw new Error(`Failed to get history: ${response.statusText}`);
        }

        const data = await response.json();
        setHistory(data.entries || []);
        return data.entries || [];
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to get history';
        setError(message);
        return [];
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl],
  );

  /**
   * Restore a pruned item
   */
  const restoreItem = useCallback(
    async (nodeId: string): Promise<boolean> => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(`${getBaseUrl()}/api/knowledge/mound/pruning/restore`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace_id: workspaceId, node_id: nodeId }),
        });

        if (!response.ok) {
          throw new Error(`Failed to restore item: ${response.statusText}`);
        }

        const result = await response.json();
        return result.success;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to restore item';
        setError(message);
        return false;
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl],
  );

  /**
   * Apply confidence decay
   */
  const applyConfidenceDecay = useCallback(
    async (decayRate = 0.01, minConfidence = 0.1): Promise<number> => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(`${getBaseUrl()}/api/knowledge/mound/pruning/decay`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workspace_id: workspaceId,
            decay_rate: decayRate,
            min_confidence: minConfidence,
          }),
        });

        if (!response.ok) {
          throw new Error(`Failed to apply decay: ${response.statusText}`);
        }

        const result = await response.json();
        return result.items_decayed || 0;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to apply decay';
        setError(message);
        return 0;
      } finally {
        setIsLoading(false);
      }
    },
    [workspaceId, getBaseUrl],
  );

  /**
   * Clear state
   */
  const clearState = useCallback(() => {
    setPrunableItems([]);
    setHistory([]);
    setLastResult(null);
    setError(null);
  }, []);

  return {
    // State
    prunableItems,
    history,
    lastResult,
    isLoading,
    error,

    // Actions
    getPrunableItems,
    pruneItems,
    autoPrune,
    getHistory,
    restoreItem,
    applyConfidenceDecay,
    clearState,
  };
}
