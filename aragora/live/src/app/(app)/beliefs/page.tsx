'use client';

import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import { logger } from '@/utils/logger';
import { DebateThisButton } from '@/components/DebateThisButton';
import {
  useBeliefNetwork,
  type BeliefNode,
  type BeliefNetworkGraph,
} from '@/hooks/useBeliefNetwork';

// ============================================================================
// Types
// ============================================================================

interface RecentDebate {
  debate_id: string;
  topic: string;
  created_at: string;
  agent_count: number;
}

// ============================================================================
// Sub-components
// ============================================================================

function ConfidenceBar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? 'bg-[var(--acid-green)]' : pct >= 40 ? 'bg-yellow-400' : 'bg-red-400';

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-theme-data text-[var(--text-muted)] w-16 shrink-0">
        {label}
      </span>
      <div className="flex-1 h-2 bg-[var(--bg)] rounded overflow-hidden">
        <div className={`h-full ${color} rounded transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-theme-data text-[var(--text)] w-10 text-right">{pct}%</span>
    </div>
  );
}

function NodeCard({
  node,
  selected,
  onClick,
}: {
  node: BeliefNode;
  selected: boolean;
  onClick: () => void;
}) {
  const centralityPct = Math.round(node.centrality * 100);

  return (
    <div
      onClick={onClick}
      className={`p-4 border rounded cursor-pointer transition-all hover:border-[var(--acid-green)]/60 ${
        selected
          ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/5'
          : 'border-[var(--border)] bg-[var(--surface)]/30'
      }`}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <p className="font-theme-data text-sm text-[var(--text)] line-clamp-2 flex-1">
          {node.statement}
        </p>
        <div className="flex gap-1 shrink-0 items-center">
          {node.is_crux && (
            <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-red-500/20 text-red-400 border border-red-500/30 rounded">
              CRUX
            </span>
          )}
          <DebateThisButton
            question={node.statement}
            source="beliefs"
            context={`Belief claim by ${node.author} with centrality ${Math.round(node.centrality * 100)}%`}
            variant="icon"
          />
        </div>
      </div>

      <div className="flex items-center gap-3 text-xs font-theme-data text-[var(--text-muted)]">
        <span>
          Agent: <span className="text-[var(--acid-cyan)]">{node.author}</span>
        </span>
        <span>|</span>
        <span>
          Centrality:{' '}
          <span
            className={
              centralityPct >= 70
                ? 'text-[var(--acid-green)]'
                : centralityPct >= 40
                  ? 'text-yellow-400'
                  : 'text-[var(--text)]'
            }
          >
            {centralityPct}%
          </span>
        </span>
        {node.crux_score !== undefined && node.crux_score !== null && (
          <>
            <span>|</span>
            <span>
              Crux Score: <span className="text-red-400">{Math.round(node.crux_score * 100)}%</span>
            </span>
          </>
        )}
      </div>

      {node.belief && (
        <div className="mt-3 space-y-1">
          <ConfidenceBar value={node.belief.true_prob} label="True" />
          <ConfidenceBar value={node.belief.false_prob} label="False" />
          <ConfidenceBar value={node.belief.uncertain_prob} label="Unsure" />
        </div>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="p-12 border border-[var(--border)] rounded bg-[var(--surface)]/30 text-center">
      <div className="text-4xl mb-4 font-theme-data">{'\u0394'}</div>
      <h3 className="font-theme-data text-lg text-[var(--text)] mb-2">No Belief Networks Yet</h3>
      <p className="font-theme-data text-sm text-[var(--text-muted)] max-w-md mx-auto mb-4">
        Belief networks are built from debate traces. Run a debate first, then select it here to
        explore the claims, cruxes, and evidence relationships.
      </p>
      <a
        href="/arena"
        className="inline-block px-4 py-2 bg-[var(--acid-green)] text-[var(--bg)] font-theme-data text-sm hover:bg-[var(--acid-green)]/80 transition-colors"
      >
        START A DEBATE
      </a>
    </div>
  );
}

// ============================================================================
// Main Page
// ============================================================================

export default function BeliefsPage() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();

  const {
    graph,
    loadBearingClaims,
    cruxAnalysis,
    claimSupport,
    loading,
    error,
    fetchGraph,
    fetchLoadBearingClaims,
    fetchCruxes,
    fetchClaimSupport,
  } = useBeliefNetwork();

  // Recent debates for selection
  const [recentDebates, setRecentDebates] = useState<RecentDebate[]>([]);
  const [debatesLoading, setDebatesLoading] = useState(false);
  const [selectedDebateId, setSelectedDebateId] = useState<string>('');
  const [selectedNode, setSelectedNode] = useState<BeliefNode | null>(null);

  // Tab state
  const [activeTab, setActiveTab] = useState<'graph' | 'cruxes' | 'load-bearing' | 'support'>(
    'graph',
  );

  // Fetch recent debates on mount
  const fetchRecentDebates = useCallback(async () => {
    setDebatesLoading(true);
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const res = await fetch(`${backendConfig.api}/api/debates?limit=20`, { headers });
      if (res.ok) {
        const data = await res.json();
        const debates = (data.debates || data.items || []).map((d: Record<string, unknown>) => ({
          debate_id: d.id || d.debate_id || '',
          topic: d.topic || d.question || d.task || 'Untitled',
          created_at: d.created_at || '',
          agent_count: (d.agents as string[] | undefined)?.length || 0,
        }));
        setRecentDebates(debates);
      }
    } catch (err) {
      logger.error('Failed to fetch recent debates:', err);
      // Provide demo data
      setRecentDebates([
        {
          debate_id: 'demo-001',
          topic: 'Should we adopt microservices architecture?',
          created_at: new Date().toISOString(),
          agent_count: 3,
        },
        {
          debate_id: 'demo-002',
          topic: 'Is remote work more productive?',
          created_at: new Date(Date.now() - 86400000).toISOString(),
          agent_count: 4,
        },
      ]);
    } finally {
      setDebatesLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token]);

  useEffect(() => {
    fetchRecentDebates();
  }, [fetchRecentDebates]);

  // Load belief network when debate selected
  const handleSelectDebate = useCallback(
    async (debateId: string) => {
      setSelectedDebateId(debateId);
      setSelectedNode(null);
      await fetchGraph(debateId);
    },
    [fetchGraph],
  );

  // Load tab data
  useEffect(() => {
    if (!selectedDebateId) return;
    if (activeTab === 'cruxes') {
      fetchCruxes(selectedDebateId);
    } else if (activeTab === 'load-bearing') {
      fetchLoadBearingClaims(selectedDebateId);
    }
  }, [activeTab, selectedDebateId, fetchCruxes, fetchLoadBearingClaims]);

  // Load claim support when node selected
  const handleNodeSelect = useCallback(
    async (node: BeliefNode) => {
      setSelectedNode(node);
      if (selectedDebateId && activeTab === 'support') {
        await fetchClaimSupport(selectedDebateId, node.claim_id);
      }
    },
    [selectedDebateId, activeTab, fetchClaimSupport],
  );

  // Switch to support tab when clicking a node
  const handleViewSupport = useCallback(
    async (node: BeliefNode) => {
      setSelectedNode(node);
      setActiveTab('support');
      if (selectedDebateId) {
        await fetchClaimSupport(selectedDebateId, node.claim_id);
      }
    },
    [selectedDebateId, fetchClaimSupport],
  );

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6 max-w-7xl">
          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--acid-green)] mb-1">
              {'>'} BELIEFS &amp; PREDICTIONS
            </h1>
            <p className="text-[var(--text-muted)] font-theme-data text-sm">
              Explore belief networks built from debate traces. View claims, crux points,
              load-bearing arguments, and evidence support chains.
            </p>
          </div>

          {/* Debate Selector */}
          <div className="mb-6 p-4 border border-[var(--border)] rounded bg-[var(--surface)]/30">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-theme-data text-sm text-[var(--acid-green)]">SELECT DEBATE</h2>
              <button
                onClick={fetchRecentDebates}
                disabled={debatesLoading}
                className="px-3 py-1 text-xs font-theme-data border border-[var(--acid-green)]/30 text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors disabled:opacity-50"
              >
                {debatesLoading ? '[LOADING...]' : '[REFRESH]'}
              </button>
            </div>

            {recentDebates.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {recentDebates.map((debate) => (
                  <button
                    key={debate.debate_id}
                    onClick={() => handleSelectDebate(debate.debate_id)}
                    className={`px-3 py-2 text-xs font-theme-data border rounded transition-colors text-left max-w-xs truncate ${
                      selectedDebateId === debate.debate_id
                        ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10 text-[var(--acid-green)]'
                        : 'border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)]/40'
                    }`}
                    title={debate.topic}
                  >
                    {debate.topic}
                  </button>
                ))}
              </div>
            ) : debatesLoading ? (
              <div className="text-center py-4 text-[var(--acid-green)] font-theme-data animate-pulse text-sm">
                Loading debates...
              </div>
            ) : (
              <p className="text-sm font-theme-data text-[var(--text-muted)]">
                No recent debates found. Start a debate to build belief networks.
              </p>
            )}
          </div>

          {/* Error Banner */}
          {error && (
            <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded text-red-400 text-sm font-theme-data">
              {error}
            </div>
          )}

          {/* Main Content */}
          {!selectedDebateId ? (
            <EmptyState />
          ) : (
            <>
              {/* Tab Navigation */}
              <div className="flex gap-2 mb-6">
                {(
                  [
                    { id: 'graph' as const, label: 'CLAIM GRAPH' },
                    { id: 'cruxes' as const, label: 'CRUX POINTS' },
                    { id: 'load-bearing' as const, label: 'LOAD-BEARING' },
                    { id: 'support' as const, label: 'EVIDENCE SUPPORT' },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                      activeTab === tab.id
                        ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10 text-[var(--acid-green)]'
                        : 'border-[var(--acid-green)]/30 text-[var(--text-muted)] hover:text-[var(--text)]'
                    }`}
                  >
                    [{tab.label}]
                  </button>
                ))}
              </div>

              {/* Loading */}
              {loading && (
                <div className="text-center py-8 text-[var(--acid-green)] font-theme-data animate-pulse">
                  Loading belief network...
                </div>
              )}

              {/* Graph Tab -- Claims List */}
              {activeTab === 'graph' && !loading && (
                <PanelErrorBoundary panelName="Belief Network Graph">
                  <GraphTab
                    graph={graph}
                    selectedNode={selectedNode}
                    onNodeSelect={handleNodeSelect}
                    onViewSupport={handleViewSupport}
                  />
                </PanelErrorBoundary>
              )}

              {/* Cruxes Tab */}
              {activeTab === 'cruxes' && !loading && (
                <PanelErrorBoundary panelName="Crux Analysis">
                  <CruxesTab cruxAnalysis={cruxAnalysis} />
                </PanelErrorBoundary>
              )}

              {/* Load-Bearing Tab */}
              {activeTab === 'load-bearing' && !loading && (
                <PanelErrorBoundary panelName="Load-Bearing Claims">
                  <LoadBearingTab claims={loadBearingClaims} />
                </PanelErrorBoundary>
              )}

              {/* Support Tab */}
              {activeTab === 'support' && !loading && (
                <PanelErrorBoundary panelName="Evidence Support">
                  <SupportTab
                    selectedNode={selectedNode}
                    claimSupport={claimSupport}
                    graph={graph}
                    onNodeSelect={handleViewSupport}
                  />
                </PanelErrorBoundary>
              )}
            </>
          )}

          {/* Footer */}
          <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
            <div className="text-[var(--acid-green)]/50 mb-2">{'='.repeat(40)}</div>
            <p className="text-[var(--text-muted)]">{'>'} ARAGORA // BELIEFS &amp; PREDICTIONS</p>
          </footer>
        </div>
      </main>
    </>
  );
}

// ============================================================================
// Tab Components
// ============================================================================

function GraphTab({
  graph,
  selectedNode,
  onNodeSelect,
  onViewSupport,
}: {
  graph: BeliefNetworkGraph | null;
  selectedNode: BeliefNode | null;
  onNodeSelect: (node: BeliefNode) => void;
  onViewSupport: (node: BeliefNode) => void;
}) {
  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="p-8 border border-[var(--border)] rounded text-center">
        <p className="font-theme-data text-[var(--text-muted)]">No claims found for this debate.</p>
        <p className="font-theme-data text-[var(--text-muted)]/60 text-xs mt-2">
          The debate trace may not have generated belief network data.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Stats Bar */}
      <div className="lg:col-span-3">
        <div className="grid grid-cols-3 gap-3">
          <div className="p-3 border border-[var(--acid-green)]/30 rounded bg-[var(--surface)]/30 text-center">
            <div className="text-2xl font-theme-data text-[var(--acid-green)]">
              {graph.metadata.total_claims}
            </div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">Total Claims</div>
          </div>
          <div className="p-3 border border-[var(--acid-green)]/30 rounded bg-[var(--surface)]/30 text-center">
            <div className="text-2xl font-theme-data text-red-400">{graph.metadata.crux_count}</div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">Crux Points</div>
          </div>
          <div className="p-3 border border-[var(--acid-green)]/30 rounded bg-[var(--surface)]/30 text-center">
            <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
              {graph.links.length}
            </div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">Relationships</div>
          </div>
        </div>
      </div>

      {/* Claims List */}
      <div className="lg:col-span-2 space-y-3 max-h-[600px] overflow-y-auto pr-2">
        {graph.nodes
          .sort((a, b) => b.centrality - a.centrality)
          .map((node) => (
            <NodeCard
              key={node.id}
              node={node}
              selected={selectedNode?.id === node.id}
              onClick={() => onNodeSelect(node)}
            />
          ))}
      </div>

      {/* Detail Panel */}
      <div>
        {selectedNode ? (
          <div className="p-4 border border-[var(--acid-green)]/30 rounded bg-[var(--surface)]/30 sticky top-24">
            <h3 className="font-theme-data text-sm text-[var(--acid-green)] mb-3">CLAIM DETAILS</h3>
            <p className="font-theme-data text-sm text-[var(--text)] mb-4">
              {selectedNode.statement}
            </p>

            <div className="grid grid-cols-2 gap-3 mb-4">
              <div className="p-2 bg-[var(--bg)] rounded">
                <div className="text-[10px] text-[var(--text-muted)]">AUTHOR</div>
                <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                  {selectedNode.author}
                </div>
              </div>
              <div className="p-2 bg-[var(--bg)] rounded">
                <div className="text-[10px] text-[var(--text-muted)]">CENTRALITY</div>
                <div className="font-theme-data text-sm text-[var(--text)]">
                  {Math.round(selectedNode.centrality * 100)}%
                </div>
              </div>
            </div>

            {selectedNode.belief && (
              <div className="mb-4 space-y-1.5">
                <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-1">
                  BELIEF DISTRIBUTION
                </div>
                <ConfidenceBar value={selectedNode.belief.true_prob} label="True" />
                <ConfidenceBar value={selectedNode.belief.false_prob} label="False" />
                <ConfidenceBar value={selectedNode.belief.uncertain_prob} label="Unsure" />
              </div>
            )}

            {/* Related links */}
            {graph && (
              <div className="border-t border-[var(--border)] pt-3">
                <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-2">
                  RELATIONSHIPS
                </div>
                {graph.links
                  .filter((l) => l.source === selectedNode.id || l.target === selectedNode.id)
                  .slice(0, 8)
                  .map((link, i) => {
                    const otherId = link.source === selectedNode.id ? link.target : link.source;
                    const otherNode = graph.nodes.find((n) => n.id === otherId);
                    return (
                      <div key={i} className="flex items-center justify-between py-1 text-xs">
                        <span className="font-theme-data text-[var(--text-muted)] truncate max-w-[180px]">
                          {otherNode?.statement?.slice(0, 40) || otherId}...
                        </span>
                        <span className="font-theme-data text-[var(--acid-cyan)] shrink-0 ml-2">
                          {Math.round(link.weight * 100)}%
                        </span>
                      </div>
                    );
                  })}
              </div>
            )}

            <button
              onClick={() => onViewSupport(selectedNode)}
              className="mt-4 w-full px-3 py-2 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
            >
              VIEW EVIDENCE SUPPORT
            </button>
          </div>
        ) : (
          <div className="p-8 border border-[var(--border)] rounded text-center text-[var(--text-muted)] font-theme-data text-sm">
            Select a claim to view details
          </div>
        )}
      </div>
    </div>
  );
}

function CruxesTab({
  cruxAnalysis,
}: {
  cruxAnalysis: ReturnType<typeof useBeliefNetwork>['cruxAnalysis'];
}) {
  if (!cruxAnalysis || !cruxAnalysis.cruxes?.length) {
    return (
      <div className="p-8 border border-[var(--border)] rounded text-center">
        <p className="font-theme-data text-[var(--text-muted)]">
          No crux points detected for this debate.
        </p>
        <p className="font-theme-data text-[var(--text-muted)]/60 text-xs mt-2">
          Cruxes are claims where changing belief would most affect the debate outcome.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="font-theme-data text-sm text-[var(--text-muted)]">
        Crux points are claims that, if resolved differently, would most change the debate outcome.
        High crux scores indicate pivotal arguments.
      </p>
      {cruxAnalysis.cruxes.map((crux, idx) => (
        <div
          key={crux.claim_id}
          className="p-4 border border-red-500/20 rounded bg-red-900/5 hover:border-red-500/40 transition-colors"
        >
          <div className="flex items-start justify-between gap-4 mb-3">
            <div className="flex items-center gap-2">
              <span className="font-theme-data text-lg text-red-400 font-bold">#{idx + 1}</span>
              <p className="font-theme-data text-sm text-[var(--text)]">{crux.statement}</p>
            </div>
            <span className="px-2 py-1 text-xs font-theme-data bg-red-500/20 text-red-400 border border-red-500/30 rounded shrink-0">
              {Math.round(crux.crux_score * 100)}%
            </span>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="p-2 bg-[var(--bg)] rounded">
              <div className="text-[10px] font-theme-data text-[var(--text-muted)]">INFLUENCE</div>
              <div className="font-theme-data text-sm text-[var(--acid-green)]">
                {Math.round(crux.influence * 100)}%
              </div>
            </div>
            <div className="p-2 bg-[var(--bg)] rounded">
              <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                DISAGREEMENT
              </div>
              <div className="font-theme-data text-sm text-orange-400">
                {Math.round(crux.disagreement * 100)}%
              </div>
            </div>
            <div className="p-2 bg-[var(--bg)] rounded">
              <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                UNCERTAINTY
              </div>
              <div className="font-theme-data text-sm text-yellow-400">
                {Math.round(crux.uncertainty * 100)}%
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function LoadBearingTab({
  claims,
}: {
  claims: ReturnType<typeof useBeliefNetwork>['loadBearingClaims'];
}) {
  if (!claims || claims.length === 0) {
    return (
      <div className="p-8 border border-[var(--border)] rounded text-center">
        <p className="font-theme-data text-[var(--text-muted)]">No load-bearing claims found.</p>
        <p className="font-theme-data text-[var(--text-muted)]/60 text-xs mt-2">
          Load-bearing claims have the highest centrality in the belief network, meaning many other
          claims depend on them.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="font-theme-data text-sm text-[var(--text-muted)]">
        Load-bearing claims have the highest centrality -- many other arguments depend on them. If
        they fall, the argument structure collapses.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full font-theme-data text-sm">
          <thead>
            <tr className="border-b border-[var(--acid-green)]/30">
              <th className="py-2 px-3 text-[var(--acid-green)] text-left">#</th>
              <th className="py-2 px-3 text-[var(--acid-green)] text-left">Claim</th>
              <th className="py-2 px-3 text-[var(--acid-green)] text-left">Author</th>
              <th className="py-2 px-3 text-[var(--acid-green)] text-right">Centrality</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim, idx) => (
              <tr
                key={claim.claim_id}
                className={`border-b border-[var(--acid-green)]/10 ${
                  idx % 2 === 0 ? 'bg-[var(--acid-green)]/5' : ''
                }`}
              >
                <td className="py-2 px-3 text-[var(--text-muted)]">{idx + 1}</td>
                <td className="py-2 px-3 text-[var(--text)]">{claim.statement}</td>
                <td className="py-2 px-3 text-[var(--acid-cyan)]">{claim.author}</td>
                <td className="py-2 px-3 text-right">
                  <span
                    className={
                      claim.centrality >= 0.7
                        ? 'text-[var(--acid-green)]'
                        : claim.centrality >= 0.4
                          ? 'text-yellow-400'
                          : 'text-[var(--text)]'
                    }
                  >
                    {Math.round(claim.centrality * 100)}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SupportTab({
  selectedNode,
  claimSupport,
  graph,
  onNodeSelect,
}: {
  selectedNode: BeliefNode | null;
  claimSupport: ReturnType<typeof useBeliefNetwork>['claimSupport'];
  graph: BeliefNetworkGraph | null;
  onNodeSelect: (node: BeliefNode) => void;
}) {
  if (!selectedNode) {
    return (
      <div className="space-y-4">
        <p className="font-theme-data text-sm text-[var(--text-muted)]">
          Select a claim from the Graph tab to view its evidence support chain.
        </p>
        {graph && graph.nodes.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {graph.nodes.slice(0, 6).map((node) => (
              <button
                key={node.id}
                onClick={() => onNodeSelect(node)}
                className="p-3 border border-[var(--border)] rounded text-left hover:border-[var(--acid-green)]/40 transition-colors"
              >
                <p className="font-theme-data text-xs text-[var(--text)] line-clamp-2">
                  {node.statement}
                </p>
                <span className="font-theme-data text-[10px] text-[var(--text-muted)] mt-1 block">
                  by {node.author}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Selected claim */}
      <div className="p-4 border border-[var(--acid-green)]/30 rounded bg-[var(--surface)]/30">
        <div className="text-[10px] font-theme-data text-[var(--acid-green)] mb-1">
          SELECTED CLAIM
        </div>
        <p className="font-theme-data text-sm text-[var(--text)]">{selectedNode.statement}</p>
        <span className="font-theme-data text-xs text-[var(--text-muted)] mt-1 block">
          by {selectedNode.author} | centrality: {Math.round(selectedNode.centrality * 100)}%
        </span>
      </div>

      {/* Support data */}
      {claimSupport?.support ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="p-3 border border-[var(--border)] rounded bg-[var(--surface)]/30 text-center">
            <div className="text-2xl font-theme-data text-[var(--acid-green)]">
              {claimSupport.support.supporting}
            </div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">Supporting</div>
          </div>
          <div className="p-3 border border-[var(--border)] rounded bg-[var(--surface)]/30 text-center">
            <div className="text-2xl font-theme-data text-red-400">
              {claimSupport.support.contradicting}
            </div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">Contradicting</div>
          </div>
          <div className="p-3 border border-[var(--border)] rounded bg-[var(--surface)]/30 text-center">
            <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
              {claimSupport.support.evidence_count}
            </div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">Evidence Total</div>
          </div>
          <div className="p-3 border border-[var(--border)] rounded bg-[var(--surface)]/30 text-center">
            <div className="text-2xl font-theme-data text-[var(--text)]">
              {Math.round(claimSupport.support.confidence * 100)}%
            </div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">Confidence</div>
          </div>
        </div>
      ) : claimSupport?.message ? (
        <div className="p-4 border border-[var(--border)] rounded text-center">
          <p className="font-theme-data text-sm text-[var(--text-muted)]">{claimSupport.message}</p>
        </div>
      ) : (
        <div className="p-4 border border-[var(--border)] rounded text-center">
          <p className="font-theme-data text-sm text-[var(--text-muted)]">
            No provenance data available for this claim.
          </p>
        </div>
      )}
    </div>
  );
}
