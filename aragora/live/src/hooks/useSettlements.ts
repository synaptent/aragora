'use client';

import { useSWRFetch, type UseSWRFetchOptions } from './useSWRFetch';

/**
 * Shape of a single settlement record from the API.
 */
export interface SettlementRecord {
  debate_id: string;
  settled_at: string;
  confidence: number;
  falsifiers: string[];
  alternatives: string[];
  review_horizon: string;
  cruxes: string[];
  status: 'settled' | 'due_review' | 'invalidated' | 'confirmed';
  review_notes: string[];
  reviewed_at: string | null;
  reviewed_by: string | null;
  /** Blockchain anchoring status (populated when ERC-8004 integration is active) */
  anchor_hash?: string | null;
  anchor_chain_id?: number | null;
  anchor_local_only?: boolean;
}

/**
 * Summary response from /api/v1/settlements/summary
 */
export interface SettlementSummary {
  total: number;
  by_status: Record<string, number>;
  due_for_review: number;
  average_confidence: number;
  recent: SettlementRecord[];
}

/**
 * Hook to fetch settlement lifecycle data for the dashboard.
 *
 * @param options - SWR fetch options (refreshInterval, etc.)
 * @returns Settlement summary data, due count, and loading/error state.
 */
export function useSettlements(options?: UseSWRFetchOptions<SettlementSummary>) {
  const { data, error, isLoading, isValidating, mutate } = useSWRFetch<SettlementSummary>(
    '/api/v1/settlements/summary',
    {
      refreshInterval: 60000, // Refresh every 60 seconds
      ...options,
    },
  );

  return {
    summary: data,
    dueCount: data?.due_for_review ?? 0,
    isLoading,
    isValidating,
    error,
    mutate,
  };
}
