'use client';

import { useState, useEffect, useCallback } from 'react';
import { LearningEvolution } from './LearningEvolution';
import { ErrorWithRetry } from './RetryButton';
import { withErrorBoundary } from './PanelErrorBoundary';
import { fetchWithRetry } from '@/utils/retry';
import type { StreamEvent, GenericStreamEvent } from '@/types/events';
import { API_BASE_URL } from '@/config';

interface Insight {
  id: string;
  type: string;
  title: string;
  description: string;
  confidence: number;
  agents_involved: string[];
  evidence: string[];
}

interface MemoryRecall {
  query: string;
  hits: Array<{ topic: string; similarity: number }>;
  count: number;
  timestamp: string;
}

interface FlipEvent {
  id: string;
  agent: string;
  type: 'contradiction' | 'retraction' | 'qualification' | 'refinement';
  type_emoji: string;
  before: { claim: string; confidence: string };
  after: { claim: string; confidence: string };
  similarity: string;
  domain: string | null;
  timestamp: string;
}

interface FlipSummary {
  total_flips: number;
  by_type: Record<string, number>;
  by_agent: Record<string, number>;
  recent_24h: number;
}

interface InsightsPanelProps {
  wsMessages?: StreamEvent[];
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

function InsightsPanelComponent({
  wsMessages = [],
  apiBase = DEFAULT_API_BASE,
}: InsightsPanelProps) {
  const [insights, setInsights] = useState<Insight[]>([]);
  const [memoryRecalls, setMemoryRecalls] = useState<MemoryRecall[]>([]);
  const [flips, setFlips] = useState<FlipEvent[]>([]);
  const [flipSummary, setFlipSummary] = useState<FlipSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'insights' | 'memory' | 'flips' | 'learning'>(
    'insights',
  );

  const fetchInsights = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetchWithRetry(`${apiBase}/api/insights/recent?limit=10`, undefined, {
        maxRetries: 2,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const data = await response.json();
      setInsights(data.insights || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch insights');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  const fetchFlips = useCallback(async () => {
    // Use allSettled to handle partial failures gracefully
    const [flipsResult, summaryResult] = await Promise.allSettled([
      fetchWithRetry(`${apiBase}/api/flips/recent?limit=15`, undefined, { maxRetries: 2 }),
      fetchWithRetry(`${apiBase}/api/flips/summary`, undefined, { maxRetries: 2 }),
    ]);

    if (flipsResult.status === 'fulfilled' && flipsResult.value.ok) {
      const flipsData = await flipsResult.value.json();
      setFlips(flipsData.flips || []);
    }

    if (summaryResult.status === 'fulfilled' && summaryResult.value.ok) {
      const summaryData = await summaryResult.value.json();
      setFlipSummary(summaryData.summary || null);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchInsights();
    fetchFlips();
  }, [fetchInsights, fetchFlips]);

  // Listen for memory_recall WebSocket events
  useEffect(() => {
    const recallMessages: MemoryRecall[] = wsMessages
      .filter((msg) => msg.type === 'memory_recall')
      .map((msg) => {
        const data = msg.data as Record<string, unknown>;
        return {
          query: (data.query as string) || '',
          hits: (data.hits as Array<{ topic: string; similarity: number }>) || [],
          count: (data.count as number) || 0,
          timestamp: msg.timestamp
            ? new Date(msg.timestamp).toISOString()
            : new Date().toISOString(),
        };
      });

    if (recallMessages.length > 0) {
      setMemoryRecalls((prev) => {
        const newRecalls = [...recallMessages, ...prev].slice(0, 20);
        return newRecalls;
      });
    }
  }, [wsMessages]);

  // Listen for flip_detected WebSocket events for real-time flip updates
  useEffect(() => {
    const typeEmojis: Record<string, string> = {
      contradiction: '🔄',
      retraction: '↩️',
      qualification: '⚖️',
      refinement: '✨',
    };

    const flipMessages: FlipEvent[] = wsMessages
      .filter((msg) => msg.type === 'flip_detected')
      .map((msg) => {
        const data = (msg.data || {}) as Record<string, unknown>;
        const beforeData = data.before as Record<string, unknown> | undefined;
        const afterData = data.after as Record<string, unknown> | undefined;
        const flipType = String(data.flip_type || data.type || 'unknown');
        const origConf = data.original_confidence as number | undefined;
        const newConf = data.new_confidence as number | undefined;
        const simScore = data.similarity_score as number | undefined;

        return {
          id: String(data.id || `flip-${Date.now()}-${Math.random().toString(36).slice(2)}`),
          agent: String(data.agent_name || data.agent || 'unknown'),
          type: flipType as FlipEvent['type'],
          type_emoji: typeEmojis[flipType] || '❓',
          before: {
            claim: String(data.original_claim || beforeData?.claim || ''),
            confidence: origConf
              ? `${(origConf * 100).toFixed(0)}%`
              : String(beforeData?.confidence || 'N/A'),
          },
          after: {
            claim: String(data.new_claim || afterData?.claim || ''),
            confidence: newConf
              ? `${(newConf * 100).toFixed(0)}%`
              : String(afterData?.confidence || 'N/A'),
          },
          similarity: simScore
            ? `${(simScore * 100).toFixed(0)}%`
            : String(data.similarity || 'N/A'),
          domain: data.domain ? String(data.domain) : null,
          timestamp: msg.timestamp
            ? new Date(msg.timestamp).toISOString()
            : String(data.detected_at || new Date().toISOString()),
        };
      });

    if (flipMessages.length > 0) {
      setFlips((prev) => {
        // Deduplicate by ID and keep newest first
        const existingIds = new Set(prev.map((f) => f.id));
        const newFlips = flipMessages.filter((f) => !existingIds.has(f.id));
        return [...newFlips, ...prev].slice(0, 50);
      });
      // Auto-switch to flips tab when new flip detected
      if (activeTab !== 'flips') {
        setActiveTab('flips');
      }
    }
  }, [wsMessages, activeTab]);

  const getTypeColor = (type: string): string => {
    switch (type) {
      case 'consensus':
        return 'bg-green-500/20 text-green-400 border-green-500/30';
      case 'pattern':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      case 'agent_performance':
        return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
      case 'divergence':
        return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
      default:
        return 'bg-zinc-500/20 text-zinc-500 dark:text-zinc-400 border-zinc-500/30';
    }
  };

  const getConfidenceColor = (confidence: number): string => {
    if (confidence >= 0.8) return 'text-green-400';
    if (confidence >= 0.6) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getFlipTypeColor = (type: string): string => {
    switch (type) {
      case 'contradiction':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'retraction':
        return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
      case 'qualification':
        return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
      case 'refinement':
        return 'bg-green-500/20 text-green-400 border-green-500/30';
      default:
        return 'bg-zinc-500/20 text-zinc-500 dark:text-zinc-400 border-zinc-500/30';
    }
  };

  return (
    <div className="panel">
      <div className="panel-header mb-4">
        <h3 className="panel-title">Debate Insights</h3>
        <button
          onClick={fetchInsights}
          className="px-2 py-1 bg-surface border border-border rounded text-sm text-text hover:bg-surface-hover"
        >
          Refresh
        </button>
      </div>

      {/* Tab Navigation */}
      <div role="tablist" aria-label="Insights categories" className="panel-tabs mb-4">
        <button
          role="tab"
          aria-selected={activeTab === 'insights'}
          aria-controls="insights-panel"
          id="insights-tab"
          onClick={() => setActiveTab('insights')}
          className={`px-3 py-1 rounded text-sm transition-colors flex-1 focus:outline-none focus:ring-2 focus:ring-accent ${
            activeTab === 'insights'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Insights ({insights.length})
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'memory'}
          aria-controls="memory-panel"
          id="memory-tab"
          onClick={() => setActiveTab('memory')}
          className={`px-3 py-1 rounded text-sm transition-colors flex-1 focus:outline-none focus:ring-2 focus:ring-accent ${
            activeTab === 'memory'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Memory ({memoryRecalls.length})
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'flips'}
          aria-controls="flips-panel"
          id="flips-tab"
          onClick={() => setActiveTab('flips')}
          className={`px-3 py-1 rounded text-sm transition-colors flex-1 focus:outline-none focus:ring-2 focus:ring-accent ${
            activeTab === 'flips'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Flips ({flips.length})
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'learning'}
          aria-controls="learning-panel"
          id="learning-tab"
          onClick={() => setActiveTab('learning')}
          className={`px-3 py-1 rounded text-sm transition-colors flex-1 focus:outline-none focus:ring-2 focus:ring-accent ${
            activeTab === 'learning'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Learning
        </button>
      </div>

      {/* Key Disagreements (crux detection) */}
      {wsMessages.filter((e): e is GenericStreamEvent => e.type === 'crux_detected').length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-2">
            KEY DISAGREEMENTS
          </h3>
          <div className="space-y-2">
            {wsMessages
              .filter((e): e is GenericStreamEvent => e.type === 'crux_detected')
              .map((e, i) => (
                <div
                  key={i}
                  className="p-2 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded"
                >
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                    {typeof e.data === 'object' && e.data !== null && 'description' in e.data
                      ? String(e.data.description)
                      : 'Critical disagreement point detected'}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Insights Tab */}
      {activeTab === 'insights' && (
        <div
          id="insights-panel"
          role="tabpanel"
          aria-labelledby="insights-tab"
          className="space-y-3 max-h-96 overflow-y-auto"
        >
          {loading && <div className="text-center text-text-muted py-4">Loading insights...</div>}

          {error && <ErrorWithRetry error={error} onRetry={fetchInsights} />}

          {!loading && !error && insights.length === 0 && (
            <div className="text-center text-text-muted py-4">
              No insights extracted yet. Run a debate cycle to generate insights.
            </div>
          )}

          {insights.map((insight) => (
            <div
              key={insight.id}
              className="p-3 bg-bg border border-border rounded-lg hover:border-accent/50 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <span
                  className={`px-2 py-0.5 text-xs rounded border ${getTypeColor(insight.type)}`}
                >
                  {insight.type}
                </span>
                <span
                  className={`text-xs font-theme-data ${getConfidenceColor(insight.confidence)}`}
                >
                  {(insight.confidence * 100).toFixed(0)}%
                </span>
              </div>

              <h4 className="text-sm font-medium text-text mt-2">{insight.title}</h4>

              <p className="text-xs text-text-muted mt-1">{insight.description}</p>

              {insight.agents_involved?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {insight.agents_involved.map((agent, i) => (
                    <span
                      key={i}
                      className="px-1.5 py-0.5 text-xs bg-surface rounded text-text-muted"
                    >
                      {agent}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Memory Recalls Tab */}
      {activeTab === 'memory' && (
        <div
          id="memory-panel"
          role="tabpanel"
          aria-labelledby="memory-tab"
          className="space-y-3 max-h-96 overflow-y-auto"
        >
          {memoryRecalls.length === 0 && (
            <div className="text-center text-text-muted py-4">
              No memory recalls yet. Historical context will appear here during debates.
            </div>
          )}

          {memoryRecalls.map((recall, index) => (
            <div
              key={`${recall.timestamp}-${index}`}
              className="p-3 bg-bg border border-border rounded-lg"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="px-2 py-0.5 text-xs bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 rounded">
                  Memory Recall
                </span>
                <span className="text-xs text-text-muted">
                  {new Date(recall.timestamp).toLocaleTimeString()}
                </span>
              </div>

              <p className="text-sm text-text-muted mb-2">Query: {recall.query}</p>

              <div className="space-y-1">
                {recall.hits?.map((hit, i) => (
                  <div key={i} className="flex justify-between text-xs">
                    <span className="text-text flex-1 mr-2">{hit.topic}</span>
                    <span className="text-text-muted font-theme-data">
                      {(hit.similarity * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>

              {recall.count > 3 && (
                <div className="text-xs text-text-muted mt-1">+{recall.count - 3} more matches</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Flips Tab */}
      {activeTab === 'flips' && (
        <div
          id="flips-panel"
          role="tabpanel"
          aria-labelledby="flips-tab"
          className="space-y-3 max-h-96 overflow-y-auto"
        >
          {/* Summary Header */}
          {flipSummary && flipSummary.total_flips > 0 && (
            <div className="p-3 bg-bg border border-border rounded-lg mb-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-text">Position Reversals</span>
                <span className="text-xs text-text-muted">{flipSummary.recent_24h} in 24h</span>
              </div>
              <div className="flex flex-wrap gap-2 text-xs">
                {flipSummary.by_type.contradiction > 0 && (
                  <span className="px-2 py-0.5 bg-red-500/20 text-red-400 rounded">
                    {flipSummary.by_type.contradiction} contradictions
                  </span>
                )}
                {flipSummary.by_type.retraction > 0 && (
                  <span className="px-2 py-0.5 bg-orange-500/20 text-orange-400 rounded">
                    {flipSummary.by_type.retraction} retractions
                  </span>
                )}
                {flipSummary.by_type.qualification > 0 && (
                  <span className="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">
                    {flipSummary.by_type.qualification} qualifications
                  </span>
                )}
                {flipSummary.by_type.refinement > 0 && (
                  <span className="px-2 py-0.5 bg-green-500/20 text-green-400 rounded">
                    {flipSummary.by_type.refinement} refinements
                  </span>
                )}
              </div>
            </div>
          )}

          {flips.length === 0 && (
            <div className="text-center text-text-muted py-4">
              No position flips detected yet. Flips are tracked when agents reverse their positions.
            </div>
          )}

          {flips.map((flip) => (
            <div
              key={flip.id}
              className="p-3 bg-bg border border-border rounded-lg hover:border-accent/50 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 text-xs rounded border ${getFlipTypeColor(flip.type)}`}
                  >
                    {flip.type_emoji} {flip.type}
                  </span>
                  <span className="text-xs text-text-muted font-theme-data">{flip.agent}</span>
                </div>
                <span className="text-xs text-text-muted">{flip.similarity} similar</span>
              </div>

              <div className="space-y-2 text-xs">
                <div className="p-2 bg-red-500/10 border border-red-500/20 rounded">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-red-400 font-medium">Before</span>
                    <span className="text-text-muted">{flip.before.confidence}</span>
                  </div>
                  <p className="text-text-muted">{flip.before.claim}</p>
                </div>

                <div className="p-2 bg-green-500/10 border border-green-500/20 rounded">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-green-400 font-medium">After</span>
                    <span className="text-text-muted">{flip.after.confidence}</span>
                  </div>
                  <p className="text-text-muted">{flip.after.claim}</p>
                </div>
              </div>

              {flip.domain && (
                <div className="mt-2">
                  <span className="px-1.5 py-0.5 text-xs bg-surface rounded text-text-muted">
                    {flip.domain}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Learning Tab */}
      {activeTab === 'learning' && (
        <div
          id="learning-panel"
          role="tabpanel"
          aria-labelledby="learning-tab"
          className="max-h-[500px] overflow-y-auto"
        >
          <LearningEvolution />
        </div>
      )}
    </div>
  );
}

// Wrap with error boundary for graceful error handling
export const InsightsPanel = withErrorBoundary(InsightsPanelComponent, 'Insights');
