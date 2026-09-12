'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { API_BASE_URL } from '@/config';
import { useAuthFetch } from '@/hooks/useAuthenticatedFetch';

const API_BASE = API_BASE_URL;

// ============================================================================
// Types
// ============================================================================

export interface BatchItem {
  question: string;
  agents?: string;
  rounds?: number;
  consensus?: string;
  priority?: number;
  metadata?: Record<string, unknown>;
}

export interface BatchSubmitRequest {
  items: BatchItem[];
  webhook_url?: string;
  webhook_headers?: Record<string, string>;
  max_parallel?: number;
}

export interface BatchSubmitResponse {
  success: boolean;
  batch_id: string;
  items_queued: number;
  status_url: string;
}

export type BatchStatusValue = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

export interface BatchItemStatus {
  index: number;
  question: string;
  status: BatchStatusValue;
  debate_id?: string;
  error?: string;
  started_at?: string;
  completed_at?: string;
}

export interface BatchStatus {
  batch_id: string;
  status: BatchStatusValue;
  total_items: number;
  completed_items: number;
  failed_items: number;
  items: BatchItemStatus[];
  created_at: string;
  updated_at: string;
  webhook_url?: string;
}

export interface BatchListItem {
  batch_id: string;
  status: BatchStatusValue;
  total_items: number;
  completed_items: number;
  failed_items: number;
  created_at: string;
}

export interface QueueStatus {
  active: boolean;
  max_concurrent?: number;
  active_count?: number;
  total_batches?: number;
  status_counts?: Record<string, number>;
  message?: string;
}

// ============================================================================
// Hook State
// ============================================================================

interface UseBatchDebateState {
  submitting: boolean;
  submitError: string | null;
  lastSubmittedBatchId: string | null;

  currentBatch: BatchStatus | null;
  batchLoading: boolean;
  batchError: string | null;

  batches: BatchListItem[];
  batchesLoading: boolean;
  batchesError: string | null;

  queueStatus: QueueStatus | null;
  queueLoading: boolean;
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Hook for managing batch debate operations
 *
 * @example
 * const batch = useBatchDebate();
 *
 * // Submit a batch
 * const result = await batch.submitBatch({
 *   items: [{ question: "Is AI safe?" }, { question: "What is consciousness?" }]
 * });
 *
 * // Poll for status
 * batch.pollBatchStatus(result.batch_id, 5000);
 */
export function useBatchDebate() {
  const { getAuthHeaders, isAuthenticated, isLoading: authLoading } = useAuthFetch();
  const [state, setState] = useState<UseBatchDebateState>({
    submitting: false,
    submitError: null,
    lastSubmittedBatchId: null,
    currentBatch: null,
    batchLoading: false,
    batchError: null,
    batches: [],
    batchesLoading: false,
    batchesError: null,
    queueStatus: null,
    queueLoading: false,
  });

  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Submit Batch
  // ---------------------------------------------------------------------------

  const submitBatch = useCallback(
    async (request: BatchSubmitRequest): Promise<BatchSubmitResponse | null> => {
      if (!isAuthenticated && !authLoading) {
        setState((s) => ({ ...s, submitError: 'Authentication required' }));
        return null;
      }

      setState((s) => ({ ...s, submitting: true, submitError: null }));

      try {
        const response = await fetch(`${API_BASE}/api/debates/batch`, {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify(request),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          const errorMsg = data.error || data.message || `HTTP ${response.status}`;
          setState((s) => ({ ...s, submitting: false, submitError: errorMsg }));
          return null;
        }

        const data: BatchSubmitResponse = await response.json();
        setState((s) => ({
          ...s,
          submitting: false,
          submitError: null,
          lastSubmittedBatchId: data.batch_id,
        }));
        return data;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to submit batch';
        setState((s) => ({ ...s, submitting: false, submitError: errorMsg }));
        return null;
      }
    },
    [isAuthenticated, authLoading, getAuthHeaders],
  );

  // ---------------------------------------------------------------------------
  // Get Batch Status
  // ---------------------------------------------------------------------------

  const getBatchStatus = useCallback(
    async (batchId: string): Promise<BatchStatus | null> => {
      setState((s) => ({ ...s, batchLoading: true, batchError: null }));

      try {
        const response = await fetch(`${API_BASE}/api/debates/batch/${batchId}/status`, {
          headers: getAuthHeaders(),
        });

        if (!response.ok) {
          if (response.status === 404) {
            setState((s) => ({ ...s, batchLoading: false, batchError: 'Batch not found' }));
            return null;
          }
          throw new Error(`HTTP ${response.status}`);
        }

        const data: BatchStatus = await response.json();
        setState((s) => ({ ...s, batchLoading: false, batchError: null, currentBatch: data }));
        return data;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to fetch batch status';
        setState((s) => ({ ...s, batchLoading: false, batchError: errorMsg }));
        return null;
      }
    },
    [getAuthHeaders],
  );

  // ---------------------------------------------------------------------------
  // Poll Batch Status
  // ---------------------------------------------------------------------------

  const pollBatchStatus = useCallback(
    (batchId: string, intervalMs: number = 5000) => {
      // Clear any existing polling
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }

      // Immediate fetch
      getBatchStatus(batchId);

      // Start polling
      pollingRef.current = setInterval(async () => {
        const status = await getBatchStatus(batchId);

        // Stop polling if batch is complete or failed
        if (
          status &&
          (status.status === 'completed' ||
            status.status === 'failed' ||
            status.status === 'cancelled')
        ) {
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
        }
      }, intervalMs);
    },
    [getBatchStatus],
  );

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  // ---------------------------------------------------------------------------
  // List Batches
  // ---------------------------------------------------------------------------

  const listBatches = useCallback(
    async (limit: number = 50, statusFilter?: BatchStatusValue): Promise<BatchListItem[]> => {
      setState((s) => ({ ...s, batchesLoading: true, batchesError: null }));

      try {
        const params = new URLSearchParams({ limit: String(limit) });
        if (statusFilter) {
          params.set('status', statusFilter);
        }

        const response = await fetch(`${API_BASE}/api/debates/batch?${params}`, {
          headers: getAuthHeaders(),
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const batches = data.batches || [];
        setState((s) => ({ ...s, batchesLoading: false, batchesError: null, batches }));
        return batches;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Failed to list batches';
        setState((s) => ({ ...s, batchesLoading: false, batchesError: errorMsg }));
        return [];
      }
    },
    [getAuthHeaders],
  );

  // ---------------------------------------------------------------------------
  // Get Queue Status
  // ---------------------------------------------------------------------------

  const getQueueStatus = useCallback(async (): Promise<QueueStatus | null> => {
    setState((s) => ({ ...s, queueLoading: true }));

    try {
      const response = await fetch(`${API_BASE}/api/debates/batch/queue`, {
        headers: getAuthHeaders(),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data: QueueStatus = await response.json();
      setState((s) => ({ ...s, queueLoading: false, queueStatus: data }));
      return data;
    } catch {
      setState((s) => ({ ...s, queueLoading: false }));
      return null;
    }
  }, [getAuthHeaders]);

  // ---------------------------------------------------------------------------
  // Clear State
  // ---------------------------------------------------------------------------

  const clearBatch = useCallback(() => {
    stopPolling();
    setState((s) => ({ ...s, currentBatch: null, batchError: null }));
  }, [stopPolling]);

  const clearSubmitError = useCallback(() => {
    setState((s) => ({ ...s, submitError: null }));
  }, []);

  // ---------------------------------------------------------------------------
  // Return
  // ---------------------------------------------------------------------------

  return {
    // State
    ...state,
    isPolling: pollingRef.current !== null,
    isAuthenticated,
    authLoading,

    // Actions
    submitBatch,
    getBatchStatus,
    pollBatchStatus,
    stopPolling,
    listBatches,
    getQueueStatus,
    clearBatch,
    clearSubmitError,

    // Computed
    progress: state.currentBatch
      ? Math.round((state.currentBatch.completed_items / state.currentBatch.total_items) * 100)
      : 0,
    isComplete: state.currentBatch?.status === 'completed',
    isFailed: state.currentBatch?.status === 'failed',
    isProcessing: state.currentBatch?.status === 'processing',
  };
}
