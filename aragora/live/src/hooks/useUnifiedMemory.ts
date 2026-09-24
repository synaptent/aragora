'use client';

import useSWR from 'swr';
import { API_BASE_URL } from '@/config';
import { useState, useCallback } from 'react';

// --- Types ---

interface MemoryResult {
  content: string;
  source: 'continuum' | 'km' | 'supermemory' | 'claude_mem';
  relevance: number;
  metadata: Record<string, unknown>;
}

interface QueryResponse {
  data: {
    results: MemoryResult[];
    total: number;
    per_system: Record<string, number>;
    query: string;
  };
}

interface RetentionDecision {
  memory_id: string;
  action: 'retain' | 'demote' | 'forget' | 'consolidate';
  surprise_score: number;
  reason: string;
  timestamp: string;
}

interface RetentionResponse {
  data: {
    decisions: RetentionDecision[];
    stats: { retained: number; demoted: number; forgotten: number; consolidated: number };
  };
}

interface DedupCluster {
  cluster_id: string;
  entries: Array<{ content: string; source: string; similarity: number }>;
  canonical: string;
}

interface DedupResponse {
  data: { clusters: DedupCluster[]; total_duplicates: number };
}

interface MemorySource {
  name: string;
  entry_count: number;
  status: 'active' | 'unavailable';
  last_activity: string | null;
}

interface SourcesResponse {
  data: { sources: MemorySource[] };
}

// --- Hooks ---

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function useUnifiedMemoryQuery() {
  const [results, setResults] = useState<MemoryResult[]>([]);
  const [perSystem, setPerSystem] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const search = useCallback(async (query: string, systems?: string[]) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/memory/unified/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          systems: systems ?? ['continuum', 'km', 'supermemory', 'claude_mem'],
          limit: 20,
        }),
      });
      const data: QueryResponse = await res.json();
      setResults(data.data?.results ?? []);
      setPerSystem(data.data?.per_system ?? {});
    } catch (e) {
      setError(e instanceof Error ? e : new Error('Query failed'));
    } finally {
      setLoading(false);
    }
  }, []);

  return { search, results, perSystem, loading, error };
}

export function useRetentionDecisions() {
  const { data, error, isLoading } = useSWR<RetentionResponse>(
    `${API_BASE_URL}/api/memory/unified/retention`,
    fetcher,
    { refreshInterval: 15000 },
  );
  return {
    decisions: data?.data?.decisions ?? [],
    stats: data?.data?.stats ?? { retained: 0, demoted: 0, forgotten: 0, consolidated: 0 },
    loading: isLoading,
    error,
  };
}

export function useDedupClusters() {
  const { data, error, isLoading } = useSWR<DedupResponse>(
    `${API_BASE_URL}/api/memory/unified/dedup`,
    fetcher,
    { refreshInterval: 30000 },
  );
  return {
    clusters: data?.data?.clusters ?? [],
    totalDuplicates: data?.data?.total_duplicates ?? 0,
    loading: isLoading,
    error,
  };
}

export function useMemorySources() {
  const { data, error, isLoading } = useSWR<SourcesResponse>(
    `${API_BASE_URL}/api/memory/unified/sources`,
    fetcher,
    { refreshInterval: 30000 },
  );
  return { sources: data?.data?.sources ?? [], loading: isLoading, error };
}
