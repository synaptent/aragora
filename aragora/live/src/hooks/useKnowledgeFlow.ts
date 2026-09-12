'use client';

import useSWR from 'swr';
import { API_BASE_URL } from '@/config';

// --- Types ---

interface FlowLink {
  source_debate_id: string;
  km_node_id: string;
  target_debate_id: string | null;
  confidence_delta: number;
  timestamp: string;
  content_preview: string;
}

interface FlowResponse {
  data: {
    flows: FlowLink[];
    stats: { total_flows: number; avg_confidence_change: number; debates_enriched: number };
  };
}

interface ConfidenceEntry {
  node_id: string;
  content_preview: string;
  confidence_history: Array<{ timestamp: string; value: number; reason: string }>;
}

interface ConfidenceResponse {
  data: { entries: ConfidenceEntry[] };
}

interface AdapterStatus {
  name: string;
  status: 'active' | 'stale' | 'offline';
  entry_count: number;
  last_sync: string | null;
  health: 'healthy' | 'degraded' | 'unhealthy';
}

interface AdapterHealthResponse {
  data: { adapters: AdapterStatus[]; total: number; active: number; stale: number };
}

// --- Hooks ---

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function useKnowledgeFlow() {
  const { data, error, isLoading, mutate } = useSWR<FlowResponse>(
    `${API_BASE_URL}/api/knowledge/flow`,
    fetcher,
    { refreshInterval: 30000 },
  );
  return {
    flows: data?.data?.flows ?? [],
    stats: data?.data?.stats ?? { total_flows: 0, avg_confidence_change: 0, debates_enriched: 0 },
    loading: isLoading,
    error,
    refresh: mutate,
  };
}

export function useConfidenceHistory() {
  const { data, error, isLoading } = useSWR<ConfidenceResponse>(
    `${API_BASE_URL}/api/knowledge/flow/confidence-history`,
    fetcher,
    { refreshInterval: 30000 },
  );
  return { entries: data?.data?.entries ?? [], loading: isLoading, error };
}

export function useAdapterHealth() {
  const { data, error, isLoading, mutate } = useSWR<AdapterHealthResponse>(
    `${API_BASE_URL}/api/knowledge/adapters/health`,
    fetcher,
    { refreshInterval: 30000 },
  );
  return {
    adapters: data?.data?.adapters ?? [],
    total: data?.data?.total ?? 0,
    active: data?.data?.active ?? 0,
    stale: data?.data?.stale ?? 0,
    loading: isLoading,
    error,
    refresh: mutate,
  };
}
