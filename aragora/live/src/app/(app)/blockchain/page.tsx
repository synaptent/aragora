'use client';
import { useState } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { ErrorWithRetry } from '@/components/ErrorWithRetry';
import {
  useBlockchainConfig,
  useBlockchainAgents,
  useBlockchainAgent,
  useBlockchainReputation,
  useBlockchainValidations,
  useBlockchainHealth,
  type OnChainAgent,
} from '@/hooks/useBlockchain';

function HealthBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    healthy: 'text-[var(--accent)] bg-[var(--accent)]/20 border-[var(--accent)]/30',
    degraded: 'text-yellow-400 bg-yellow-500/20 border-yellow-500/30',
    unavailable: 'text-red-400 bg-red-500/20 border-red-500/30',
  };
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[status] || colors.unavailable}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

function ValidationBadge({ response }: { response: number }) {
  const labels: Record<number, { text: string; color: string }> = {
    0: { text: 'PENDING', color: 'text-text-muted bg-surface' },
    1: { text: 'PASS', color: 'text-[var(--accent)] bg-[var(--accent)]/20' },
    2: { text: 'FAIL', color: 'text-red-400 bg-red-500/20' },
    3: { text: 'REVOKED', color: 'text-orange-400 bg-orange-500/20' },
  };
  const info = labels[response] || labels[0];
  return (
    <span className={`px-2 py-0.5 text-xs font-theme-data rounded ${info.color}`}>{info.text}</span>
  );
}

function AgentDetailPanel({ tokenId, onClose }: { tokenId: number; onClose: () => void }) {
  const { data: agent, isLoading: agentLoading } = useBlockchainAgent(tokenId);
  const { data: reputation } = useBlockchainReputation(tokenId);
  const { data: validations } = useBlockchainValidations(tokenId);

  if (agentLoading) {
    return (
      <div className="p-6 bg-surface border border-border rounded-lg animate-pulse">
        <span className="text-[var(--accent)] font-theme-data">Loading agent #{tokenId}...</span>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="p-6 bg-surface border border-border rounded-lg">
        <span className="text-text-muted font-theme-data">Agent not found</span>
      </div>
    );
  }

  return (
    <div className="p-6 bg-surface border-2 border-[var(--accent)]/30 rounded-lg space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-theme-data font-bold text-[var(--accent)]">
          Agent #{agent.token_id}
        </h3>
        <button
          onClick={onClose}
          className="px-3 py-1 text-xs font-theme-data border border-border rounded hover:border-[var(--accent)]/50 transition-colors"
        >
          Close
        </button>
      </div>

      {/* Identity */}
      <div className="grid md:grid-cols-2 gap-4 text-sm">
        <div>
          <div className="text-xs text-text-muted mb-1">Owner</div>
          <div className="font-theme-data text-text break-all">{agent.owner}</div>
        </div>
        <div>
          <div className="text-xs text-text-muted mb-1">Agent URI</div>
          <div className="font-theme-data text-text break-all">{agent.agent_uri}</div>
        </div>
        {agent.wallet_address && (
          <div>
            <div className="text-xs text-text-muted mb-1">Wallet</div>
            <div className="font-theme-data text-text break-all">{agent.wallet_address}</div>
          </div>
        )}
        {agent.aragora_agent_id && (
          <div>
            <div className="text-xs text-text-muted mb-1">Aragora Agent</div>
            <div className="font-theme-data text-[var(--accent)]">{agent.aragora_agent_id}</div>
          </div>
        )}
        <div>
          <div className="text-xs text-text-muted mb-1">Chain ID</div>
          <div className="font-theme-data text-text">{agent.chain_id}</div>
        </div>
        {agent.registered_at && (
          <div>
            <div className="text-xs text-text-muted mb-1">Registered</div>
            <div className="font-theme-data text-text">
              {new Date(agent.registered_at).toLocaleDateString()}
            </div>
          </div>
        )}
        {agent.tx_hash && (
          <div className="md:col-span-2">
            <div className="text-xs text-text-muted mb-1">Transaction</div>
            <div className="font-theme-data text-text text-xs break-all">{agent.tx_hash}</div>
          </div>
        )}
      </div>

      {/* Reputation & Validation */}
      <div className="grid md:grid-cols-2 gap-4">
        {reputation && (
          <div className="p-4 bg-bg rounded-lg border border-border">
            <h4 className="text-xs font-theme-data text-text-muted uppercase mb-3">Reputation</h4>
            <div className="text-3xl font-theme-data font-bold text-[var(--accent)] mb-1">
              {reputation.normalized_value.toFixed(2)}
            </div>
            <div className="text-xs text-text-muted">
              {reputation.count} feedback record{reputation.count !== 1 ? 's' : ''}
            </div>
            {(reputation.tag1 || reputation.tag2) && (
              <div className="flex gap-2 mt-2">
                {reputation.tag1 && (
                  <span className="px-2 py-0.5 text-xs font-theme-data bg-blue-500/20 text-blue-400 rounded">
                    {reputation.tag1}
                  </span>
                )}
                {reputation.tag2 && (
                  <span className="px-2 py-0.5 text-xs font-theme-data bg-purple-500/20 text-purple-400 rounded">
                    {reputation.tag2}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
        {validations && (
          <div className="p-4 bg-bg rounded-lg border border-border">
            <h4 className="text-xs font-theme-data text-text-muted uppercase mb-3">Validations</h4>
            <div className="flex items-center gap-3 mb-1">
              <span className="text-3xl font-theme-data font-bold text-text">
                {validations.count}
              </span>
              <ValidationBadge response={validations.average_response} />
            </div>
            <div className="text-xs text-text-muted">
              validation record{validations.count !== 1 ? 's' : ''}
            </div>
            {validations.tag && (
              <div className="mt-2">
                <span className="px-2 py-0.5 text-xs font-theme-data bg-cyan-500/20 text-cyan-400 rounded">
                  {validations.tag}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function BlockchainPage() {
  const [skip, setSkip] = useState(0);
  const [selectedAgent, setSelectedAgent] = useState<number | null>(null);
  const limit = 50;

  const { data: config, error: configError } = useBlockchainConfig();
  const {
    data: agents,
    isLoading: agentsLoading,
    error: agentsError,
    mutate,
  } = useBlockchainAgents(skip, limit);
  const { data: health } = useBlockchainHealth();

  const error = configError?.message || agentsError?.message;

  const chainName = (id?: number) => {
    if (!id) return 'Unknown';
    const names: Record<number, string> = {
      1: 'Ethereum Mainnet',
      5: 'Goerli',
      11155111: 'Sepolia',
      137: 'Polygon',
      80001: 'Mumbai',
      42161: 'Arbitrum One',
    };
    return names[id] || `Chain ${id}`;
  };

  return (
    <div className="min-h-screen bg-bg text-text relative overflow-hidden">
      <Scanlines />
      <CRTVignette />

      <div className="max-w-6xl mx-auto px-4 py-8 relative z-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <Link href="/" className="hover:opacity-80 transition-opacity">
            <AsciiBannerCompact />
          </Link>
          <div className="flex items-center gap-4">
            <ThemeToggle />
            <BackendSelector />
          </div>
        </div>

        {/* Title */}
        <div className="mb-8">
          <h1 className="text-3xl font-theme-data font-bold text-[var(--accent)] mb-2">
            ERC-8004 Agent Registry
          </h1>
          <p className="text-text-muted font-theme-data text-sm">
            On-chain agent identities, reputation scores, and validation records
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-6">
            <ErrorWithRetry
              error={error}
              onRetry={() => {
                mutate();
              }}
            />
          </div>
        )}

        {/* Chain Config Summary */}
        {config && (
          <div className="mb-6 p-4 bg-surface border border-border rounded-lg">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs font-theme-data text-text-muted uppercase">
                Chain Configuration
              </h2>
              <HealthBadge status={config.health?.status || 'unavailable'} />
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-text-muted">Network</div>
                <div className="font-theme-data text-text">{chainName(config.chain_id)}</div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Connected</div>
                <div
                  className={`font-theme-data ${config.is_connected ? 'text-[var(--accent)]' : 'text-red-400'}`}
                >
                  {config.is_connected ? 'Yes' : 'No'}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Confirmations</div>
                <div className="font-theme-data text-text">{config.block_confirmations}</div>
              </div>
              {config.health?.latency_ms !== undefined && (
                <div>
                  <div className="text-xs text-text-muted">Latency</div>
                  <div className="font-theme-data text-text">{config.health.latency_ms}ms</div>
                </div>
              )}
            </div>
            {/* Contract addresses */}
            <div className="mt-3 pt-3 border-t border-border grid md:grid-cols-3 gap-3 text-xs">
              <div>
                <span className="text-text-muted">Identity: </span>
                <span className="font-theme-data text-text">
                  {config.identity_registry
                    ? `${config.identity_registry.slice(0, 10)}...${config.identity_registry.slice(-6)}`
                    : 'Not configured'}
                </span>
              </div>
              <div>
                <span className="text-text-muted">Reputation: </span>
                <span className="font-theme-data text-text">
                  {config.reputation_registry
                    ? `${config.reputation_registry.slice(0, 10)}...${config.reputation_registry.slice(-6)}`
                    : 'Not configured'}
                </span>
              </div>
              <div>
                <span className="text-text-muted">Validation: </span>
                <span className="font-theme-data text-text">
                  {config.validation_registry
                    ? `${config.validation_registry.slice(0, 10)}...${config.validation_registry.slice(-6)}`
                    : 'Not configured'}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Summary Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="p-4 bg-surface border border-border rounded-lg text-center">
            <div className="text-2xl font-theme-data font-bold text-[var(--accent)]">
              {agents?.total ?? '—'}
            </div>
            <div className="text-xs font-theme-data text-text-muted">Registered Agents</div>
          </div>
          <div className="p-4 bg-surface border border-border rounded-lg text-center">
            <div className="text-2xl font-theme-data font-bold text-text">
              {config?.chain_id ?? '—'}
            </div>
            <div className="text-xs font-theme-data text-text-muted">Chain ID</div>
          </div>
          <div className="p-4 bg-surface border border-border rounded-lg text-center">
            <div
              className={`text-2xl font-theme-data font-bold ${
                health?.connector?.healthy ? 'text-[var(--accent)]' : 'text-red-400'
              }`}
            >
              {health?.connector?.available ? (health.connector.healthy ? 'OK' : 'ERR') : '—'}
            </div>
            <div className="text-xs font-theme-data text-text-muted">Connector</div>
          </div>
          <div className="p-4 bg-surface border border-border rounded-lg text-center">
            <div className="text-2xl font-theme-data font-bold text-text">
              {config?.block_confirmations ?? '—'}
            </div>
            <div className="text-xs font-theme-data text-text-muted">Block Confirmations</div>
          </div>
        </div>

        {/* Agent Detail */}
        {selectedAgent !== null && (
          <div className="mb-6">
            <AgentDetailPanel tokenId={selectedAgent} onClose={() => setSelectedAgent(null)} />
          </div>
        )}

        {/* Agent Registry List */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">
              Agent Registry
            </h2>
            {agents && agents.total > limit && (
              <div className="flex items-center gap-2">
                <button
                  disabled={skip === 0}
                  onClick={() => setSkip(Math.max(0, skip - limit))}
                  className="px-3 py-1 text-xs font-theme-data border border-border rounded hover:border-[var(--accent)]/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  Prev
                </button>
                <span className="text-xs font-theme-data text-text-muted">
                  {skip + 1}–{Math.min(skip + limit, agents.total)} of {agents.total}
                </span>
                <button
                  disabled={skip + limit >= agents.total}
                  onClick={() => setSkip(skip + limit)}
                  className="px-3 py-1 text-xs font-theme-data border border-border rounded hover:border-[var(--accent)]/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  Next
                </button>
              </div>
            )}
          </div>

          {agentsLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="text-[var(--accent)] font-theme-data animate-pulse">
                Loading agents...
              </div>
            </div>
          ) : agents && agents.agents.length > 0 ? (
            <div className="space-y-2">
              {agents.agents.map((agent: OnChainAgent) => (
                <button
                  key={agent.token_id}
                  onClick={() =>
                    setSelectedAgent(selectedAgent === agent.token_id ? null : agent.token_id)
                  }
                  className={`w-full p-4 bg-surface border rounded-lg text-left transition-all ${
                    selectedAgent === agent.token_id
                      ? 'border-[var(--accent)]/50'
                      : 'border-border hover:border-[var(--accent)]/30'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <span className="text-lg font-theme-data font-bold text-[var(--accent)]">
                        #{agent.token_id}
                      </span>
                      <span className="text-sm font-theme-data text-text truncate max-w-[200px]">
                        {agent.agent_uri}
                      </span>
                      {agent.aragora_agent_id && (
                        <span className="px-2 py-0.5 text-xs font-theme-data bg-blue-500/20 text-blue-400 rounded border border-blue-500/30">
                          Linked
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-text-muted font-theme-data">
                      <span className="truncate max-w-[120px]">
                        {agent.owner.slice(0, 6)}...{agent.owner.slice(-4)}
                      </span>
                      {agent.registered_at && (
                        <span>{new Date(agent.registered_at).toLocaleDateString()}</span>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="p-8 bg-surface border border-border rounded-lg text-center">
              <p className="text-text-muted font-theme-data mb-2">No agents registered on-chain</p>
              <p className="text-xs text-text-muted font-theme-data">
                Use the API or SDK to register agents: POST /api/v1/blockchain/agents
              </p>
            </div>
          )}
        </div>

        {/* Quick Links */}
        <div className="flex flex-wrap gap-3 pt-4 border-t border-border">
          <Link
            href="/agents"
            className="px-3 py-2 text-xs font-theme-data bg-surface text-text-muted border border-border rounded hover:border-[var(--accent)]/30 transition-colors"
          >
            Agent Management
          </Link>
          <Link
            href="/receipts"
            className="px-3 py-2 text-xs font-theme-data bg-surface text-text-muted border border-border rounded hover:border-[var(--accent)]/30 transition-colors"
          >
            Decision Receipts
          </Link>
          <Link
            href="/leaderboard"
            className="px-3 py-2 text-xs font-theme-data bg-surface text-text-muted border border-border rounded hover:border-[var(--accent)]/30 transition-colors"
          >
            Agent Leaderboard
          </Link>
          <Link
            href="/verification"
            className="px-3 py-2 text-xs font-theme-data bg-surface text-text-muted border border-border rounded hover:border-[var(--accent)]/30 transition-colors"
          >
            Verification
          </Link>
          <Link
            href="/api-docs"
            className="px-3 py-2 text-xs font-theme-data bg-surface text-text-muted border border-border rounded hover:border-[var(--accent)]/30 transition-colors"
          >
            API Docs
          </Link>
        </div>
      </div>
    </div>
  );
}
