'use client';

import { useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

// Lazy load the graph component
const BeliefNetworkGraph = dynamic(() => import('./BeliefNetworkGraph'), {
  ssr: false,
  loading: () => (
    <div className="p-4 text-center text-text-muted text-sm font-theme-data">Loading graph...</div>
  ),
});

interface Crux {
  claim_id: string;
  statement: string;
  author: string;
  crux_score: number;
  centrality: number;
  entropy: number;
  current_belief: {
    true_prob: number;
    false_prob: number;
    uncertain_prob: number;
    confidence: number;
  };
}

interface LoadBearingClaim {
  claim_id: string;
  statement: string;
  author: string;
  centrality: number;
}

interface ContestedClaim extends Crux {
  disagreement_score: number;
}

interface GraphStats {
  total_nodes: number;
  total_edges: number;
  density: number;
  avg_degree: number;
  clustering_coefficient: number;
  agent_stats: Record<
    string,
    { messages: number; critiques_given: number; critiques_received: number }
  >;
  round_stats: Record<string, { messages: number; critiques: number }>;
}

interface CruxPanelProps {
  debateId?: string;
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

export function CruxPanel({
  debateId: initialDebateId,
  apiBase = DEFAULT_API_BASE,
}: CruxPanelProps) {
  const { tokens } = useAuth();
  const [debateId, setDebateId] = useState(initialDebateId || '');
  const [cruxes, setCruxes] = useState<Crux[]>([]);
  const [loadBearingClaims, setLoadBearingClaims] = useState<LoadBearingClaim[]>([]);
  const [contestedClaims, setContestedClaims] = useState<ContestedClaim[]>([]);
  const [graphStats, setGraphStats] = useState<GraphStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    'cruxes' | 'load-bearing' | 'contested' | 'graph' | 'stats'
  >('cruxes');

  const fetchCruxData = useCallback(
    async (id: string) => {
      if (!id.trim()) {
        setError('Please enter a debate ID');
        return;
      }

      setLoading(true);
      setError(null);

      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      try {
        const [cruxesRes, lbRes, statsRes] = await Promise.all([
          fetch(`${apiBase}/api/belief-network/${id}/cruxes?top_k=10`, { headers }),
          fetch(`${apiBase}/api/belief-network/${id}/load-bearing-claims?limit=10`, { headers }),
          fetch(`${apiBase}/api/debate/${id}/graph-stats`, { headers }),
        ]);

        if (!cruxesRes.ok) {
          const data = await cruxesRes.json();
          throw new Error(data.error || `HTTP ${cruxesRes.status}`);
        }

        const cruxesData = await cruxesRes.json();
        const allCruxes = cruxesData.cruxes || [];
        setCruxes(allCruxes);

        // Derive contested claims: high entropy claims
        const contested = allCruxes
          .filter((c: Crux) => c.entropy >= 0.5)
          .map((c: Crux) => ({
            ...c,
            disagreement_score:
              c.entropy *
              (1 - Math.abs(c.current_belief?.true_prob - c.current_belief?.false_prob || 0)),
          }))
          .sort(
            (a: ContestedClaim, b: ContestedClaim) => b.disagreement_score - a.disagreement_score,
          );
        setContestedClaims(contested);

        if (lbRes.ok) {
          const lbData = await lbRes.json();
          setLoadBearingClaims(lbData.load_bearing_claims || []);
        }

        if (statsRes.ok) {
          const statsData = await statsRes.json();
          setGraphStats(statsData);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch crux data');
        setCruxes([]);
        setLoadBearingClaims([]);
        setContestedClaims([]);
        setGraphStats(null);
      } finally {
        setLoading(false);
      }
    },
    [apiBase, tokens?.access_token],
  );

  const handleExport = useCallback(
    async (format: 'json' | 'graphml' | 'csv') => {
      if (!debateId.trim() || !tokens?.access_token) return;

      setExporting(true);
      try {
        const headers: HeadersInit = {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens.access_token}`,
        };
        const response = await fetch(
          `${apiBase}/api/belief-network/${debateId}/export?format=${format}`,
          { headers },
        );
        if (!response.ok) throw new Error(`Export failed: ${response.status}`);

        const data = await response.json();

        // Create downloadable file
        let content: string;
        let mimeType: string;
        let filename: string;

        if (format === 'graphml') {
          content = data.content;
          mimeType = 'application/xml';
          filename = `belief-network-${debateId}.graphml`;
        } else if (format === 'csv') {
          // Create CSV content for nodes
          const nodesHeader = data.headers.nodes.join(',');
          const nodesRows = data.nodes_csv
            .map((n: Record<string, unknown>) =>
              data.headers.nodes.map((h: string) => JSON.stringify(n[h] ?? '')).join(','),
            )
            .join('\n');

          const edgesHeader = data.headers.edges.join(',');
          const edgesRows = data.edges_csv
            .map((e: Record<string, unknown>) =>
              data.headers.edges.map((h: string) => JSON.stringify(e[h] ?? '')).join(','),
            )
            .join('\n');

          content = `# Nodes\n${nodesHeader}\n${nodesRows}\n\n# Edges\n${edgesHeader}\n${edgesRows}`;
          mimeType = 'text/csv';
          filename = `belief-network-${debateId}.csv`;
        } else {
          content = JSON.stringify(data, null, 2);
          mimeType = 'application/json';
          filename = `belief-network-${debateId}.json`;
        }

        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Export failed');
      } finally {
        setExporting(false);
      }
    },
    [apiBase, debateId, tokens?.access_token],
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchCruxData(debateId);
  };

  const getEntropyColor = (entropy: number): string => {
    if (entropy >= 0.8) return 'text-red-400';
    if (entropy >= 0.5) return 'text-yellow-400';
    return 'text-green-400';
  };

  const getCentralityColor = (centrality: number): string => {
    if (centrality >= 0.3) return 'text-[var(--acid-cyan)]';
    if (centrality >= 0.1) return 'text-text';
    return 'text-text-muted';
  };

  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-text font-theme-data">Belief Network Analysis</h3>
        <span className="text-xs text-text-muted font-theme-data">[CRUXES]</span>
      </div>

      {/* Debate ID Input */}
      <form onSubmit={handleSubmit} className="mb-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={debateId}
            onChange={(e) => setDebateId(e.target.value)}
            placeholder="Enter debate ID..."
            className="flex-1 px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
          />
          <button
            type="submit"
            disabled={loading}
            className="px-4 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm font-bold hover:bg-[var(--accent)]/80 disabled:bg-text-muted transition-colors"
          >
            {loading ? '...' : 'ANALYZE'}
          </button>
        </div>
      </form>

      {error && (
        <div className="mb-4 p-2 bg-warning/10 border border-warning/30 rounded text-sm text-warning font-theme-data">
          {error}
        </div>
      )}

      {/* Tab Navigation */}
      {(cruxes.length > 0 || loadBearingClaims.length > 0 || debateId) && (
        <div className="flex flex-wrap gap-1 bg-bg border border-border rounded p-1 mb-4">
          <button
            onClick={() => setActiveTab('cruxes')}
            className={`px-3 py-1 rounded text-xs font-theme-data transition-colors ${
              activeTab === 'cruxes'
                ? 'bg-[var(--accent)] text-bg font-medium'
                : 'text-text-muted hover:text-text'
            }`}
          >
            CRUXES ({cruxes.length})
          </button>
          <button
            onClick={() => setActiveTab('load-bearing')}
            className={`px-3 py-1 rounded text-xs font-theme-data transition-colors ${
              activeTab === 'load-bearing'
                ? 'bg-[var(--accent)] text-bg font-medium'
                : 'text-text-muted hover:text-text'
            }`}
          >
            LOAD-BEARING ({loadBearingClaims.length})
          </button>
          <button
            onClick={() => setActiveTab('contested')}
            className={`px-3 py-1 rounded text-xs font-theme-data transition-colors ${
              activeTab === 'contested'
                ? 'bg-[var(--accent)] text-bg font-medium'
                : 'text-text-muted hover:text-text'
            }`}
          >
            CONTESTED ({contestedClaims.length})
          </button>
          <button
            onClick={() => setActiveTab('graph')}
            className={`px-3 py-1 rounded text-xs font-theme-data transition-colors ${
              activeTab === 'graph'
                ? 'bg-[var(--accent)] text-bg font-medium'
                : 'text-text-muted hover:text-text'
            }`}
          >
            GRAPH
          </button>
          <button
            onClick={() => setActiveTab('stats')}
            className={`px-3 py-1 rounded text-xs font-theme-data transition-colors ${
              activeTab === 'stats'
                ? 'bg-[var(--accent)] text-bg font-medium'
                : 'text-text-muted hover:text-text'
            }`}
          >
            STATS
          </button>
        </div>
      )}

      {/* Cruxes Tab */}
      {activeTab === 'cruxes' && (
        <div className="space-y-3 max-h-80 overflow-y-auto">
          {cruxes.length === 0 && !loading && !error && (
            <div className="text-center text-text-muted py-4 font-theme-data text-sm">
              Enter a debate ID to analyze belief network cruxes.
            </div>
          )}

          {cruxes.map((crux, index) => (
            <div
              key={crux.claim_id}
              className="p-3 bg-bg border border-border rounded-lg hover:border-[var(--acid-cyan)]/50 transition-colors"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <span className="px-2 py-0.5 text-xs bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 rounded font-theme-data">
                  CRUX #{index + 1}
                </span>
                <span className="text-xs font-theme-data text-text-muted">
                  score: {crux.crux_score.toFixed(3)}
                </span>
              </div>

              <p className="text-sm text-text mb-2 line-clamp-2">{crux.statement}</p>

              <div className="flex items-center gap-4 text-xs font-theme-data">
                <span className="text-text-muted">
                  by: <span className="text-text">{crux.author}</span>
                </span>
                <span className={getCentralityColor(crux.centrality)}>
                  centrality: {(crux.centrality * 100).toFixed(1)}%
                </span>
                <span className={getEntropyColor(crux.entropy)}>
                  entropy: {crux.entropy.toFixed(2)}
                </span>
              </div>

              {crux.current_belief && (
                <div className="mt-2 flex gap-2 text-xs font-theme-data">
                  <span className="px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded">
                    T: {(crux.current_belief.true_prob * 100).toFixed(0)}%
                  </span>
                  <span className="px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded">
                    F: {(crux.current_belief.false_prob * 100).toFixed(0)}%
                  </span>
                  <span className="px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">
                    ?: {(crux.current_belief.uncertain_prob * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Load-Bearing Tab */}
      {activeTab === 'load-bearing' && (
        <div className="space-y-3 max-h-80 overflow-y-auto">
          {loadBearingClaims.length === 0 && !loading && !error && (
            <div className="text-center text-text-muted py-4 font-theme-data text-sm">
              No load-bearing claims found for this debate.
            </div>
          )}

          {loadBearingClaims.map((claim, index) => (
            <div
              key={claim.claim_id}
              className="p-3 bg-bg border border-border rounded-lg hover:border-[var(--accent)]/50 transition-colors"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <span className="px-2 py-0.5 text-xs bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30 rounded font-theme-data">
                  #{index + 1} STRUCTURAL
                </span>
                <span className={`text-xs font-theme-data ${getCentralityColor(claim.centrality)}`}>
                  centrality: {(claim.centrality * 100).toFixed(1)}%
                </span>
              </div>

              <p className="text-sm text-text mb-2 line-clamp-2">{claim.statement}</p>

              <div className="text-xs font-theme-data text-text-muted">
                by: <span className="text-text">{claim.author}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Contested Tab */}
      {activeTab === 'contested' && (
        <div className="space-y-3 max-h-80 overflow-y-auto">
          {contestedClaims.length === 0 && !loading && !error && (
            <div className="text-center text-text-muted py-4 font-theme-data text-sm">
              No contested claims found. These are claims with high disagreement between agents.
            </div>
          )}

          {contestedClaims.map((claim, index) => (
            <div
              key={claim.claim_id}
              className="p-3 bg-bg border border-border rounded-lg hover:border-red-500/50 transition-colors"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <span className="px-2 py-0.5 text-xs bg-red-500/20 text-red-400 border border-red-500/30 rounded font-theme-data">
                  #{index + 1} CONTESTED
                </span>
                <span className="text-xs font-theme-data text-red-400">
                  disagreement: {(claim.disagreement_score * 100).toFixed(0)}%
                </span>
              </div>

              <p className="text-sm text-text mb-2 line-clamp-2">{claim.statement}</p>

              <div className="flex items-center gap-4 text-xs font-theme-data">
                <span className="text-text-muted">
                  by: <span className="text-text">{claim.author}</span>
                </span>
                <span className={getEntropyColor(claim.entropy)}>
                  entropy: {claim.entropy.toFixed(2)}
                </span>
              </div>

              {claim.current_belief && (
                <div className="mt-2 flex gap-2 text-xs font-theme-data">
                  <span className="px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded">
                    T: {(claim.current_belief.true_prob * 100).toFixed(0)}%
                  </span>
                  <span className="px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded">
                    F: {(claim.current_belief.false_prob * 100).toFixed(0)}%
                  </span>
                  <span className="px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">
                    ?: {(claim.current_belief.uncertain_prob * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Graph Tab */}
      {activeTab === 'graph' && (
        <div>
          {debateId ? (
            <BeliefNetworkGraph debateId={debateId} apiBase={apiBase} />
          ) : (
            <div className="text-center text-text-muted py-8 font-theme-data text-sm">
              Enter a debate ID and click ANALYZE to view the belief network graph.
            </div>
          )}
        </div>
      )}

      {/* Stats Tab */}
      {activeTab === 'stats' && (
        <div className="space-y-4">
          {!graphStats && !loading && (
            <div className="text-center text-text-muted py-4 font-theme-data text-sm">
              Enter a debate ID and click ANALYZE to view graph statistics.
            </div>
          )}

          {graphStats && (
            <>
              {/* Overview */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="p-3 bg-bg border border-border rounded">
                  <div className="text-xs text-text-muted font-theme-data uppercase mb-1">
                    Nodes
                  </div>
                  <div className="text-xl font-theme-data text-[var(--accent)]">
                    {graphStats.total_nodes}
                  </div>
                </div>
                <div className="p-3 bg-bg border border-border rounded">
                  <div className="text-xs text-text-muted font-theme-data uppercase mb-1">
                    Edges
                  </div>
                  <div className="text-xl font-theme-data text-[var(--acid-cyan)]">
                    {graphStats.total_edges}
                  </div>
                </div>
                <div className="p-3 bg-bg border border-border rounded">
                  <div className="text-xs text-text-muted font-theme-data uppercase mb-1">
                    Density
                  </div>
                  <div className="text-xl font-theme-data text-yellow-400">
                    {(graphStats.density * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="p-3 bg-bg border border-border rounded">
                  <div className="text-xs text-text-muted font-theme-data uppercase mb-1">
                    Avg Degree
                  </div>
                  <div className="text-xl font-theme-data text-text">
                    {graphStats.avg_degree.toFixed(1)}
                  </div>
                </div>
              </div>

              {/* Agent Stats */}
              {graphStats.agent_stats && Object.keys(graphStats.agent_stats).length > 0 && (
                <div className="p-3 bg-bg border border-border rounded">
                  <h4 className="text-xs font-theme-data text-text-muted uppercase mb-3">
                    Agent Participation
                  </h4>
                  <div className="space-y-2">
                    {Object.entries(graphStats.agent_stats).map(([agent, stats]) => (
                      <div
                        key={agent}
                        className="flex items-center justify-between text-sm font-theme-data"
                      >
                        <span className="text-text">{agent}</span>
                        <div className="flex gap-4 text-text-muted text-xs">
                          <span>{stats.messages} msgs</span>
                          <span className="text-green-400">{stats.critiques_given} given</span>
                          <span className="text-red-400">{stats.critiques_received} received</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Round Stats */}
              {graphStats.round_stats && Object.keys(graphStats.round_stats).length > 0 && (
                <div className="p-3 bg-bg border border-border rounded">
                  <h4 className="text-xs font-theme-data text-text-muted uppercase mb-3">
                    Round Activity
                  </h4>
                  <div className="flex gap-2 flex-wrap">
                    {Object.entries(graphStats.round_stats).map(([round, stats]) => (
                      <div
                        key={round}
                        className="px-3 py-2 bg-surface border border-border rounded text-xs font-theme-data"
                      >
                        <div className="text-text-muted">Round {round}</div>
                        <div className="text-text">
                          {stats.messages} msgs / {stats.critiques} crit
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Export Section */}
      {debateId && (cruxes.length > 0 || loadBearingClaims.length > 0) && (
        <div className="mt-4 p-3 bg-bg border border-border rounded-lg">
          <div className="flex items-center justify-between">
            <span className="text-xs font-theme-data text-text-muted uppercase">
              Export Network
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => handleExport('json')}
                disabled={exporting}
                className="px-3 py-1 text-xs font-theme-data bg-surface border border-border rounded hover:border-[var(--accent)]/50 transition-colors disabled:opacity-50"
              >
                JSON
              </button>
              <button
                onClick={() => handleExport('graphml')}
                disabled={exporting}
                className="px-3 py-1 text-xs font-theme-data bg-surface border border-border rounded hover:border-[var(--accent)]/50 transition-colors disabled:opacity-50"
              >
                GraphML
              </button>
              <button
                onClick={() => handleExport('csv')}
                disabled={exporting}
                className="px-3 py-1 text-xs font-theme-data bg-surface border border-border rounded hover:border-[var(--accent)]/50 transition-colors disabled:opacity-50"
              >
                CSV
              </button>
            </div>
          </div>
          {exporting && (
            <div className="mt-2 text-xs font-theme-data text-[var(--accent)] animate-pulse">
              Exporting...
            </div>
          )}
        </div>
      )}

      {/* Help text */}
      <div className="mt-4 text-xs text-text-muted font-theme-data border-t border-border pt-3">
        <p>
          <span className="text-[var(--acid-cyan)]">Cruxes:</span> Claims with high uncertainty and
          high centrality - resolving these would most impact the debate outcome.
        </p>
        <p className="mt-1">
          <span className="text-[var(--accent)]">Load-bearing:</span> Claims that many other claims
          depend on - foundational to the argument structure.
        </p>
        <p className="mt-1">
          <span className="text-red-400">Contested:</span> Claims with high disagreement between
          agents - areas of active debate.
        </p>
      </div>
    </div>
  );
}
