'use client';
import { useSWRFetch } from '@/hooks/useSWRFetch';

// --- Types ---

export interface ChainConfig {
  chain_id: number;
  rpc_url: string;
  identity_registry: string | null;
  reputation_registry: string | null;
  validation_registry: string | null;
  block_confirmations: number;
  is_connected: boolean;
  health: {
    status: 'healthy' | 'degraded' | 'unavailable';
    last_check?: number;
    latency_ms?: number;
  };
}

export interface OnChainAgent {
  token_id: number;
  owner: string;
  agent_uri: string;
  wallet_address: string | null;
  aragora_agent_id: string | null;
  chain_id: number;
  registered_at: string | null;
  tx_hash: string | null;
}

export interface AgentListResponse {
  total: number;
  skip: number;
  limit: number;
  count: number;
  agents: OnChainAgent[];
}

export interface ReputationSummary {
  agent_id: number;
  count: number;
  summary_value: number;
  summary_value_decimals: number;
  normalized_value: number;
  tag1: string;
  tag2: string;
}

export interface ValidationSummary {
  agent_id: number;
  count: number;
  average_response: number;
  tag: string;
}

export interface BlockchainHealth {
  connector: { name: string; available: boolean; healthy: boolean; error?: string };
  adapter: { error?: string };
}

// --- Hooks ---

export function useBlockchainConfig() {
  return useSWRFetch<ChainConfig>('/api/v1/blockchain/config', { refreshInterval: 60000 });
}

export function useBlockchainAgents(skip = 0, limit = 50) {
  return useSWRFetch<AgentListResponse>(`/api/v1/blockchain/agents?skip=${skip}&limit=${limit}`, {
    refreshInterval: 60000,
  });
}

export function useBlockchainAgent(tokenId: number | null) {
  return useSWRFetch<OnChainAgent>(
    tokenId !== null ? `/api/v1/blockchain/agents/${tokenId}` : null,
  );
}

export function useBlockchainReputation(tokenId: number | null) {
  return useSWRFetch<ReputationSummary>(
    tokenId !== null ? `/api/v1/blockchain/agents/${tokenId}/reputation` : null,
  );
}

export function useBlockchainValidations(tokenId: number | null) {
  return useSWRFetch<ValidationSummary>(
    tokenId !== null ? `/api/v1/blockchain/agents/${tokenId}/validations` : null,
  );
}

export function useBlockchainHealth() {
  return useSWRFetch<BlockchainHealth>('/api/v1/blockchain/health', { refreshInterval: 30000 });
}
