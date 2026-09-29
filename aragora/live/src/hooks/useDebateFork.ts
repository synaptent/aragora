'use client';

import { useState, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

// ============================================================================
// Types
// ============================================================================

export interface ForkNode {
  id: string;
  type: 'root' | 'fork';
  branch_point: number;
  pivot_claim?: string;
  status?: string;
  modified_context?: string;
  messages_inherited?: number;
  created_at?: number;
  children: ForkNode[];
}

export interface ForkData {
  branch_id: string;
  parent_debate_id: string;
  branch_point: number;
  pivot_claim?: string;
  modified_context?: string;
  status: string;
  messages_inherited: number;
  created_at?: number;
}

export interface ForkTree {
  id: string;
  type: 'root' | 'fork';
  branch_point: number;
  children: ForkNode[];
  total_nodes: number;
  max_depth: number;
}

export interface ForkResult {
  success: boolean;
  branch_id: string;
  parent_debate_id: string;
  branch_point: number;
  messages_inherited: number;
  modified_context?: string;
  status: string;
  message: string;
}

export interface ForkComparisonData {
  leftFork: ForkNode;
  rightFork: ForkNode;
  divergencePoint: number;
  sharedMessages: number;
  outcomeDiff: Array<{ field: string; left: unknown; right: unknown }>;
}

// ============================================================================
// Hook State
// ============================================================================

interface UseDebateForkState {
  forks: ForkData[];
  forkTree: ForkTree | null;
  loading: boolean;
  error: string | null;

  forkResult: ForkResult | null;
  forking: boolean;
  forkError: string | null;
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Hook for managing debate forks and visualizing fork trees
 *
 * @example
 * const fork = useDebateFork(debateId);
 *
 * // Load forks
 * await fork.loadForks();
 *
 * // Create a new fork
 * await fork.createFork(3, "What if we assumed the opposite?");
 *
 * // Select nodes for comparison
 * fork.selectForComparison(node1, 0);
 * fork.selectForComparison(node2, 1);
 */
export function useDebateFork(debateId: string) {
  const [state, setState] = useState<UseDebateForkState>({
    forks: [],
    forkTree: null,
    loading: false,
    error: null,
    forkResult: null,
    forking: false,
    forkError: null,
  });

  const [selectedNodes, setSelectedNodes] = useState<[ForkNode | null, ForkNode | null]>([
    null,
    null,
  ]);

  // ---------------------------------------------------------------------------
  // Load Forks
  // ---------------------------------------------------------------------------

  const loadForks = useCallback(async (): Promise<void> => {
    if (!debateId) return;

    setState((s) => ({ ...s, loading: true, error: null }));

    try {
      const response = await fetch(`${API_BASE}/api/debates/${debateId}/forks`);

      if (!response.ok) {
        if (response.status === 404) {
          // No forks yet - not an error
          setState((s) => ({ ...s, loading: false, forks: [], forkTree: null }));
          return;
        }
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }

      const data = await response.json();
      setState((s) => ({
        ...s,
        loading: false,
        forks: data.forks || [],
        forkTree: data.tree || null,
      }));
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : 'Failed to load forks';
      setState((s) => ({ ...s, loading: false, error: errorMsg }));
    }
  }, [debateId]);

  // ---------------------------------------------------------------------------
  // Create Fork
  // ---------------------------------------------------------------------------

  const createFork = useCallback(
    async (branchPoint: number, modifiedContext?: string): Promise<ForkResult | null> => {
      if (!debateId) return null;

      setState((s) => ({ ...s, forking: true, forkError: null }));

      try {
        const response = await fetch(`${API_BASE}/api/debates/${debateId}/fork`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ branch_point: branchPoint, modified_context: modifiedContext }),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `HTTP ${response.status}`);
        }

        const result: ForkResult = await response.json();
        setState((s) => ({ ...s, forking: false, forkResult: result }));

        // Refresh forks list after creating
        await loadForks();

        return result;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to create fork';
        setState((s) => ({ ...s, forking: false, forkError: errorMsg }));
        return null;
      }
    },
    [debateId, loadForks],
  );

  // ---------------------------------------------------------------------------
  // Selection for Comparison
  // ---------------------------------------------------------------------------

  const selectForComparison = useCallback((node: ForkNode, slot: 0 | 1) => {
    setSelectedNodes((prev) => {
      const next: [ForkNode | null, ForkNode | null] = [...prev];
      next[slot] = node;
      return next;
    });
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedNodes([null, null]);
  }, []);

  // ---------------------------------------------------------------------------
  // Comparison Data
  // ---------------------------------------------------------------------------

  const comparisonData = useMemo((): ForkComparisonData | null => {
    const [left, right] = selectedNodes;
    if (!left || !right) return null;

    // Find common ancestor / divergence point
    const divergencePoint = Math.min(left.branch_point || 0, right.branch_point || 0);

    const sharedMessages = divergencePoint;

    // Calculate outcome differences
    const outcomeDiff: ForkComparisonData['outcomeDiff'] = [];

    if (left.status !== right.status) {
      outcomeDiff.push({ field: 'status', left: left.status, right: right.status });
    }
    if (left.pivot_claim !== right.pivot_claim) {
      outcomeDiff.push({ field: 'pivot_claim', left: left.pivot_claim, right: right.pivot_claim });
    }
    if (left.messages_inherited !== right.messages_inherited) {
      outcomeDiff.push({
        field: 'messages_inherited',
        left: left.messages_inherited,
        right: right.messages_inherited,
      });
    }

    return { leftFork: left, rightFork: right, divergencePoint, sharedMessages, outcomeDiff };
  }, [selectedNodes]);

  // ---------------------------------------------------------------------------
  // Clear State
  // ---------------------------------------------------------------------------

  const clearError = useCallback(() => {
    setState((s) => ({ ...s, error: null, forkError: null }));
  }, []);

  const clearForkResult = useCallback(() => {
    setState((s) => ({ ...s, forkResult: null }));
  }, []);

  // ---------------------------------------------------------------------------
  // Return
  // ---------------------------------------------------------------------------

  return {
    // State
    ...state,

    // Selected nodes for comparison
    selectedNodes,

    // Actions
    loadForks,
    createFork,
    selectForComparison,
    clearSelection,
    clearError,
    clearForkResult,

    // Computed
    comparisonData,
    hasForks: state.forks.length > 0,
    hasSelection: selectedNodes[0] !== null || selectedNodes[1] !== null,
    canCompare: selectedNodes[0] !== null && selectedNodes[1] !== null,
  };
}
