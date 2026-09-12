'use client';

import { useState, useEffect, useCallback } from 'react';
import { ErrorWithRetry } from './RetryButton';
import { fetchWithRetry } from '@/utils/retry';
import { ForceGraph } from './ForceGraph';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

// Import from extracted modules
import {
  EvidenceCitationCard,
  RiskWarningCard,
  GraphLegend,
  SOURCE_TYPE_CONFIG,
  type DissentRecord,
  type ContrarianView,
  type RiskWarning,
  type ConsensusStats,
  type EvidenceCitation,
  type GraphNode,
} from './evidence-visualizer';

interface BackendConfig {
  apiUrl: string;
  wsUrl: string;
}

interface EvidenceVisualizerPanelProps {
  backendConfig?: BackendConfig;
}

const DEFAULT_API_BASE = API_BASE_URL;

export function EvidenceVisualizerPanel({ backendConfig }: EvidenceVisualizerPanelProps) {
  const apiBase = backendConfig?.apiUrl || DEFAULT_API_BASE;

  const [dissents, setDissents] = useState<DissentRecord[]>([]);
  const [contrarianViews, setContrarianViews] = useState<ContrarianView[]>([]);
  const [riskWarnings, setRiskWarnings] = useState<RiskWarning[]>([]);
  const [consensusStats, setConsensusStats] = useState<ConsensusStats | null>(null);
  const [evidence, setEvidence] = useState<EvidenceCitation[]>([]);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [apiUnavailable, setApiUnavailable] = useState(false);
  const [activeTab, setActiveTab] = useState<'dissent' | 'evidence' | 'graph'>('dissent');
  const [searchDebateId, setSearchDebateId] = useState('');
  const [topicFilter, setTopicFilter] = useState('');

  const fetchDissentData = useCallback(async () => {
    try {
      setLoading(true);

      const topicParam = topicFilter ? `&topic=${encodeURIComponent(topicFilter)}` : '';
      const [dissentsRes, contrarianRes, warningsRes, statsRes] = await Promise.allSettled([
        fetchWithRetry(`${apiBase}/api/consensus/dissents?limit=20${topicParam}`, undefined, {
          maxRetries: 2,
        }),
        fetchWithRetry(
          `${apiBase}/api/consensus/contrarian-views?limit=15${topicParam}`,
          undefined,
          { maxRetries: 2 },
        ),
        fetchWithRetry(`${apiBase}/api/consensus/risk-warnings?limit=10`, undefined, {
          maxRetries: 2,
        }),
        fetchWithRetry(`${apiBase}/api/consensus/stats`, undefined, { maxRetries: 2 }),
      ]);

      // Track if any API call succeeded
      let anySuccess = false;

      if (dissentsRes.status === 'fulfilled' && dissentsRes.value.ok) {
        const data = await dissentsRes.value.json();
        setDissents(data.dissents || []);
        anySuccess = true;
      } else {
        setDissents([]);
      }

      if (contrarianRes.status === 'fulfilled' && contrarianRes.value.ok) {
        const data = await contrarianRes.value.json();
        setContrarianViews(data.views || []);
        anySuccess = true;
      } else {
        setContrarianViews([]);
      }

      if (warningsRes.status === 'fulfilled' && warningsRes.value.ok) {
        const data = await warningsRes.value.json();
        setRiskWarnings(data.warnings || []);
        anySuccess = true;
      } else {
        setRiskWarnings([]);
      }

      if (statsRes.status === 'fulfilled' && statsRes.value.ok) {
        const data = await statsRes.value.json();
        setConsensusStats(data);
        anySuccess = true;
      }

      setApiUnavailable(!anySuccess);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch dissent data');
    } finally {
      setLoading(false);
    }
  }, [apiBase, topicFilter]);

  const fetchEvidence = useCallback(async () => {
    if (!searchDebateId.trim()) {
      setEvidence([]);
      setEvidenceError(null);
      return;
    }

    setEvidenceError(null);
    try {
      const response = await fetchWithRetry(
        `${apiBase}/api/debates/${searchDebateId}/evidence`,
        undefined,
        { maxRetries: 2 },
      );

      if (response.ok) {
        const data = await response.json();
        setEvidence(data.evidence || data.citations || []);
      } else {
        setEvidence([]);
        if (response.status === 404) {
          // Not an error - just no evidence found
        } else {
          setEvidenceError(`Failed to fetch evidence (${response.status})`);
        }
      }
    } catch (err) {
      logger.error('Failed to fetch evidence:', err);
      setEvidence([]);
      setEvidenceError('Unable to fetch evidence. Please check your connection.');
    }
  }, [apiBase, searchDebateId]);

  const fetchGraphNodes = useCallback(async () => {
    if (!searchDebateId.trim()) {
      setGraphNodes([]);
      setGraphError(null);
      return;
    }

    setGraphError(null);
    try {
      const response = await fetchWithRetry(
        `${apiBase}/api/debates/graph/${searchDebateId}/nodes`,
        undefined,
        { maxRetries: 2 },
      );

      if (response.ok) {
        const data = await response.json();
        setGraphNodes(data.nodes || []);
      } else {
        setGraphNodes([]);
        if (response.status === 404) {
          // Not an error - just no graph found
        } else {
          setGraphError(`Failed to fetch graph nodes (${response.status})`);
        }
      }
    } catch (err) {
      logger.error('Failed to fetch graph nodes:', err);
      setGraphNodes([]);
      setGraphError('Unable to fetch argument graph. Please check your connection.');
    }
  }, [apiBase, searchDebateId]);

  useEffect(() => {
    fetchDissentData();
  }, [fetchDissentData]);

  useEffect(() => {
    if (activeTab === 'evidence') {
      const debounce = setTimeout(fetchEvidence, 300);
      return () => clearTimeout(debounce);
    }
  }, [searchDebateId, activeTab, fetchEvidence]);

  useEffect(() => {
    if (activeTab === 'graph') {
      const debounce = setTimeout(fetchGraphNodes, 300);
      return () => clearTimeout(debounce);
    }
  }, [searchDebateId, activeTab, fetchGraphNodes]);

  if (loading && dissents.length === 0) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3">
          <div className="animate-spin w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
          <span className="font-theme-data text-text-muted">Loading evidence data...</span>
        </div>
      </div>
    );
  }

  if (error && dissents.length === 0) {
    return (
      <ErrorWithRetry
        error={error || 'Failed to load evidence and dissent data'}
        onRetry={fetchDissentData}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* API Unavailable Indicator */}
      {apiUnavailable && (
        <div className="bg-warning/10 border border-warning/30 rounded px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-warning">⚠</span>
            <span className="font-theme-data text-sm text-warning">
              Evidence API unavailable - No data to display
            </span>
          </div>
          <button
            onClick={fetchDissentData}
            className="font-theme-data text-xs text-warning hover:text-warning/80 transition-colors"
          >
            [RETRY]
          </button>
        </div>
      )}

      {/* Stats Overview */}
      {consensusStats && (
        <div className="card p-4">
          <h3 className="font-theme-data text-[var(--accent)] mb-4">Consensus Overview</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="text-center">
              <div className="text-3xl font-theme-data text-[var(--accent)]">
                {consensusStats.total_topics}
              </div>
              <div className="text-xs font-theme-data text-text-muted">Total Topics</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-theme-data text-[var(--acid-cyan)]">
                {consensusStats.total_dissents}
              </div>
              <div className="text-xs font-theme-data text-text-muted">Total Dissents</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-theme-data text-[var(--acid-yellow)]">
                {(consensusStats.avg_confidence * 100).toFixed(1)}%
              </div>
              <div className="text-xs font-theme-data text-text-muted">Avg Confidence</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-theme-data text-acid-red">{riskWarnings.length}</div>
              <div className="text-xs font-theme-data text-text-muted">Active Warnings</div>
            </div>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-[var(--accent)]/20 pb-2">
        {(['dissent', 'evidence', 'graph'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-theme-data text-sm transition-colors ${
              activeTab === tab
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab === 'dissent'
              ? 'DISSENT & CONTRARIAN'
              : tab === 'evidence'
                ? 'EVIDENCE TRAIL'
                : 'ARGUMENT GRAPH'}
          </button>
        ))}
      </div>

      {/* Dissent Tab */}
      {activeTab === 'dissent' && (
        <div className="space-y-6">
          {/* Topic Filter */}
          <div className="card p-4">
            <label className="block font-theme-data text-xs text-text-muted mb-2">
              Filter by Topic
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={topicFilter}
                onChange={(e) => setTopicFilter(e.target.value)}
                placeholder="Search topics..."
                className="flex-1 bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
              <button
                onClick={fetchDissentData}
                className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors"
              >
                Search
              </button>
            </div>
          </div>

          {/* Risk Warnings */}
          {riskWarnings.length > 0 && (
            <div className="card p-4 border-l-4 border-acid-red">
              <h3 className="font-theme-data text-acid-red mb-4 flex items-center gap-2">
                Risk Warnings ({riskWarnings.length})
              </h3>
              <div className="space-y-3">
                {riskWarnings.map((warning, idx) => (
                  <RiskWarningCard key={idx} warning={warning} />
                ))}
              </div>
            </div>
          )}

          {/* Dissenting Views */}
          <div className="card p-4">
            <h3 className="font-theme-data text-[var(--acid-yellow)] mb-4">
              Dissenting Views ({dissents.length})
            </h3>
            {dissents.length === 0 ? (
              <p className="text-text-muted font-theme-data text-sm">
                No dissenting views recorded yet. Dissents are captured when agents disagree during
                debates.
              </p>
            ) : (
              <div className="space-y-4">
                {dissents.map((dissent, idx) => (
                  <div key={idx} className="p-4 bg-surface rounded border border-acid-yellow/30">
                    <div className="mb-3">
                      <div className="font-theme-data text-xs text-[var(--acid-cyan)] mb-1">
                        Topic
                      </div>
                      <div className="font-theme-data text-sm text-text">{dissent.topic}</div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="p-3 bg-[var(--accent)]/10 rounded">
                        <div className="font-theme-data text-xs text-[var(--accent)] mb-1">
                          Majority View
                        </div>
                        <p className="font-theme-data text-sm text-text line-clamp-3">
                          {dissent.majority_view}
                        </p>
                      </div>

                      <div className="p-3 bg-acid-yellow/10 rounded">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-theme-data text-xs text-[var(--acid-yellow)]">
                            Dissenting View
                          </span>
                          <span className="font-theme-data text-xs text-text-muted">
                            by {dissent.dissenting_agent}
                          </span>
                        </div>
                        <p className="font-theme-data text-sm text-text line-clamp-3">
                          {dissent.dissenting_view}
                        </p>
                      </div>
                    </div>

                    {dissent.reasoning && (
                      <div className="mt-3 p-2 bg-surface/50 rounded">
                        <div className="font-theme-data text-xs text-text-muted mb-1">
                          Reasoning
                        </div>
                        <p className="font-theme-data text-xs text-text">{dissent.reasoning}</p>
                      </div>
                    )}

                    <div className="mt-2 flex items-center gap-4">
                      <span className="font-theme-data text-xs text-text-muted">
                        Confidence: {(dissent.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Contrarian Views */}
          {contrarianViews.length > 0 && (
            <div className="card p-4">
              <h3 className="font-theme-data text-[var(--acid-cyan)] mb-4">
                Contrarian Perspectives ({contrarianViews.length})
              </h3>
              <div className="space-y-3">
                {contrarianViews.map((view, idx) => (
                  <div
                    key={idx}
                    className="p-3 bg-surface rounded border border-[var(--acid-cyan)]/30"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                        {view.agent}
                      </span>
                      <span className="font-theme-data text-xs text-text-muted">
                        {(view.confidence * 100).toFixed(0)}% confident
                      </span>
                    </div>
                    <p className="font-theme-data text-sm text-text">{view.position}</p>
                    {view.reasoning && (
                      <p className="font-theme-data text-xs text-text-muted mt-2">
                        {view.reasoning}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Evidence Tab */}
      {activeTab === 'evidence' && (
        <div className="space-y-4">
          <div className="card p-4">
            <label className="block font-theme-data text-xs text-text-muted mb-2">Debate ID</label>
            <input
              type="text"
              value={searchDebateId}
              onChange={(e) => setSearchDebateId(e.target.value)}
              placeholder="Enter debate ID to view evidence trail..."
              className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </div>

          {/* Evidence Error Display */}
          {evidenceError && (
            <div className="bg-acid-red/10 border border-acid-red/30 rounded px-4 py-3 flex items-center justify-between">
              <span className="font-theme-data text-sm text-acid-red">{evidenceError}</span>
              <button
                onClick={fetchEvidence}
                className="font-theme-data text-xs text-acid-red hover:text-acid-red/80 transition-colors"
              >
                [RETRY]
              </button>
            </div>
          )}

          {/* Evidence Sources Breakdown */}
          {evidence.length > 0 && (
            <div className="card p-4">
              <h3 className="font-theme-data text-[var(--acid-cyan)] mb-3">Evidence Sources</h3>
              <div className="flex flex-wrap gap-2">
                {Object.entries(
                  evidence.reduce(
                    (acc, e) => {
                      const type = e.source_type || 'unknown';
                      acc[type] = (acc[type] || 0) + 1;
                      return acc;
                    },
                    {} as Record<string, number>,
                  ),
                ).map(([type, count]) => {
                  const config = SOURCE_TYPE_CONFIG[type] || SOURCE_TYPE_CONFIG.unknown;
                  return (
                    <span
                      key={type}
                      className={`inline-flex items-center gap-1 px-3 py-1 bg-surface rounded-full text-xs font-theme-data ${config.color} border border-current/20`}
                    >
                      <span>{config.icon}</span>
                      <span>{config.label}</span>
                      <span className="ml-1 px-1.5 py-0.5 bg-current/10 rounded-full">{count}</span>
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          <div className="card p-4">
            <h3 className="font-theme-data text-[var(--accent)] mb-4">
              Evidence Trail {evidence.length > 0 && `(${evidence.length} citations)`}
            </h3>
            {!searchDebateId ? (
              <p className="text-text-muted font-theme-data text-sm">
                Enter a debate ID to view its evidence citations and argument chain.
              </p>
            ) : evidence.length === 0 ? (
              <p className="text-text-muted font-theme-data text-sm">
                No evidence found for this debate ID.
              </p>
            ) : (
              <div className="space-y-4">
                {evidence.map((citation, idx) => (
                  <EvidenceCitationCard key={idx} citation={citation} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Graph Tab */}
      {activeTab === 'graph' && (
        <div className="space-y-4">
          <div className="card p-4">
            <label className="block font-theme-data text-xs text-text-muted mb-2">
              Graph Debate ID
            </label>
            <input
              type="text"
              value={searchDebateId}
              onChange={(e) => setSearchDebateId(e.target.value)}
              placeholder="Enter graph debate ID..."
              className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </div>

          {/* Graph Error Display */}
          {graphError && (
            <div className="bg-acid-red/10 border border-acid-red/30 rounded px-4 py-3 flex items-center justify-between">
              <span className="font-theme-data text-sm text-acid-red">{graphError}</span>
              <button
                onClick={fetchGraphNodes}
                className="font-theme-data text-xs text-acid-red hover:text-acid-red/80 transition-colors"
              >
                [RETRY]
              </button>
            </div>
          )}

          <div className="card p-4">
            <h3 className="font-theme-data text-[var(--accent)] mb-4">
              Argument Graph {graphNodes.length > 0 && `(${graphNodes.length} nodes)`}
            </h3>
            {!searchDebateId ? (
              <div className="text-center py-8">
                <p className="text-text-muted font-theme-data text-sm mb-4">
                  Enter a graph debate ID to visualize its argument structure.
                </p>
                <div className="text-xs font-theme-data text-[var(--acid-cyan)]">
                  Graph debates allow branching when agents fundamentally disagree.
                </div>
              </div>
            ) : graphNodes.length === 0 ? (
              <p className="text-text-muted font-theme-data text-sm">
                No graph nodes found for this debate ID. This may not be a graph debate.
              </p>
            ) : (
              <div className="space-y-4">
                {/* Interactive D3.js Force Graph */}
                <ForceGraph
                  nodes={graphNodes}
                  width={750}
                  height={500}
                  onNodeClick={(node) => {
                    logger.debug('Node clicked:', node.id);
                  }}
                />

                {/* Legend */}
                <GraphLegend />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-4">
        <button
          onClick={fetchDissentData}
          disabled={loading}
          className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
        >
          {loading ? 'Refreshing...' : 'Refresh Data'}
        </button>
      </div>
    </div>
  );
}
