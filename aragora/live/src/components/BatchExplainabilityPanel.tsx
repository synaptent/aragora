'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface BatchJobStatus {
  batch_id: string;
  status: 'pending' | 'processing' | 'completed' | 'partial' | 'failed';
  total_debates: number;
  processed_count: number;
  success_count: number;
  error_count: number;
  progress_pct: number;
  started_at?: number;
  completed_at?: number;
}

interface BatchDebateResult {
  debate_id: string;
  status: 'success' | 'error';
  explanation?: {
    narrative: string;
    confidence: number;
    factors: Array<{ name: string; contribution: number }>;
  };
  error?: string;
  processing_time_ms: number;
}

interface BatchResults {
  batch_id: string;
  status: string;
  results: BatchDebateResult[];
  pagination: { offset: number; limit: number; total: number; has_more: boolean };
}

interface ComparisonResult {
  debates: string[];
  common_factors: Array<{ name: string; avg_contribution: number; variance: number }>;
  divergent_factors: Array<{ name: string; contributions: Record<string, number> }>;
  overall_similarity: number;
}

interface DebateSummary {
  id: string;
  question: string;
  status: string;
  verdict?: string;
  created_at: string;
}

interface BatchExplainabilityPanelProps {
  apiBase?: string;
}

export function BatchExplainabilityPanel({
  apiBase = API_BASE_URL,
}: BatchExplainabilityPanelProps) {
  const [debates, setDebates] = useState<DebateSummary[]>([]);
  const [selectedDebates, setSelectedDebates] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [debatesLoading, setDebatesLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Batch job state
  const [activeBatch, setActiveBatch] = useState<BatchJobStatus | null>(null);
  const [batchResults, setBatchResults] = useState<BatchResults | null>(null);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);

  // Options
  const [includeEvidence, setIncludeEvidence] = useState(true);
  const [includeCounterfactuals, setIncludeCounterfactuals] = useState(false);
  const [format, setFormat] = useState<'full' | 'summary' | 'minimal'>('summary');

  // Polling interval for batch status
  const [pollingInterval, setPollingInterval] = useState<NodeJS.Timeout | null>(null);

  // Active tab
  const [activeTab, setActiveTab] = useState<'select' | 'progress' | 'results' | 'compare'>(
    'select',
  );

  // Fetch available debates
  const fetchDebates = useCallback(async () => {
    setDebatesLoading(true);
    try {
      const response = await fetch(`${apiBase}/api/debates?limit=50&status=completed`);
      if (!response.ok) throw new Error('Failed to fetch debates');
      const data = await response.json();
      setDebates(data.debates || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch debates');
      // Demo data
      setDebates([
        {
          id: 'debate-1',
          question: 'Should we use TypeScript?',
          status: 'completed',
          verdict: 'pass',
          created_at: new Date().toISOString(),
        },
        {
          id: 'debate-2',
          question: 'Is serverless better than containers?',
          status: 'completed',
          verdict: 'warn',
          created_at: new Date().toISOString(),
        },
        {
          id: 'debate-3',
          question: 'REST vs GraphQL for APIs',
          status: 'completed',
          verdict: 'pass',
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setDebatesLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchDebates();
    return () => {
      if (pollingInterval) clearInterval(pollingInterval);
    };
  }, [fetchDebates, pollingInterval]);

  // Toggle debate selection
  const toggleDebateSelection = (debateId: string) => {
    setSelectedDebates((prev) => {
      const next = new Set(prev);
      if (next.has(debateId)) {
        next.delete(debateId);
      } else {
        next.add(debateId);
      }
      return next;
    });
  };

  // Select all / deselect all
  const toggleSelectAll = () => {
    if (selectedDebates.size === debates.length) {
      setSelectedDebates(new Set());
    } else {
      setSelectedDebates(new Set(debates.map((d) => d.id)));
    }
  };

  // Start batch job
  const startBatchJob = async () => {
    if (selectedDebates.size === 0) {
      setError('Please select at least one debate');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${apiBase}/api/v1/explainability/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          debate_ids: Array.from(selectedDebates),
          options: {
            include_evidence: includeEvidence,
            include_counterfactuals: includeCounterfactuals,
            format,
          },
        }),
      });

      if (!response.ok) throw new Error('Failed to start batch job');

      const data = await response.json();
      setActiveBatch({
        batch_id: data.batch_id,
        status: data.status,
        total_debates: data.total_debates,
        processed_count: 0,
        success_count: 0,
        error_count: 0,
        progress_pct: 0,
      });

      setActiveTab('progress');
      startPolling(data.batch_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start batch job');
    } finally {
      setLoading(false);
    }
  };

  // Poll for batch status
  const startPolling = (batchId: string) => {
    if (pollingInterval) clearInterval(pollingInterval);

    const interval = setInterval(async () => {
      try {
        const response = await fetch(`${apiBase}/api/v1/explainability/batch/${batchId}/status`);
        if (!response.ok) throw new Error('Failed to fetch batch status');

        const data = await response.json();
        setActiveBatch(data);

        if (data.status === 'completed' || data.status === 'failed' || data.status === 'partial') {
          clearInterval(interval);
          setPollingInterval(null);
          if (data.status === 'completed' || data.status === 'partial') {
            fetchBatchResults(batchId);
          }
        }
      } catch {
        // Silently continue polling
      }
    }, 2000);

    setPollingInterval(interval);
  };

  // Fetch batch results
  const fetchBatchResults = async (batchId: string) => {
    try {
      const response = await fetch(`${apiBase}/api/v1/explainability/batch/${batchId}/results`);
      if (!response.ok) throw new Error('Failed to fetch results');

      const data = await response.json();
      setBatchResults(data);
      setActiveTab('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch results');
    }
  };

  // Compare explanations
  const compareExplanations = async () => {
    if (selectedDebates.size < 2) {
      setError('Select at least 2 debates to compare');
      return;
    }

    if (selectedDebates.size > 10) {
      setError('Maximum 10 debates can be compared at once');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${apiBase}/api/v1/explainability/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ debate_ids: Array.from(selectedDebates) }),
      });

      if (!response.ok) throw new Error('Failed to compare explanations');

      const data = await response.json();
      setComparison(data);
      setActiveTab('compare');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to compare explanations');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h3 className="font-theme-data text-[var(--accent)] text-lg">{'>'} BATCH EXPLAINABILITY</h3>
        <div className="text-xs font-theme-data text-text-muted">
          {selectedDebates.size} selected
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6 border-b border-[var(--accent)]/20 pb-2">
        {(['select', 'progress', 'results', 'compare'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            disabled={
              (tab === 'progress' && !activeBatch) ||
              (tab === 'results' && !batchResults) ||
              (tab === 'compare' && !comparison)
            }
            className={`px-3 py-1 text-xs font-theme-data transition-colors ${
              activeTab === tab
                ? 'border border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                : 'border border-transparent text-text-muted hover:text-[var(--accent)] disabled:opacity-30 disabled:cursor-not-allowed'
            }`}
          >
            [{tab.toUpperCase()}]
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/20 border border-red-500/50 rounded text-red-400 text-sm font-theme-data">
          {error}
          <button onClick={() => setError(null)} className="ml-4 underline">
            [DISMISS]
          </button>
        </div>
      )}

      {/* Select Tab */}
      {activeTab === 'select' && (
        <div className="space-y-4">
          {/* Options */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-4 bg-bg border border-[var(--accent)]/20">
            <div>
              <label className="flex items-center gap-2 font-theme-data text-xs text-text-muted cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeEvidence}
                  onChange={(e) => setIncludeEvidence(e.target.checked)}
                  className="w-4 h-4 accent-acid-green"
                />
                Include Evidence
              </label>
            </div>
            <div>
              <label className="flex items-center gap-2 font-theme-data text-xs text-text-muted cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeCounterfactuals}
                  onChange={(e) => setIncludeCounterfactuals(e.target.checked)}
                  className="w-4 h-4 accent-acid-green"
                />
                Include Counterfactuals
              </label>
            </div>
            <div>
              <label className="block font-theme-data text-xs text-text-muted mb-1">Format</label>
              <select
                value={format}
                onChange={(e) => setFormat(e.target.value as 'full' | 'summary' | 'minimal')}
                className="w-full bg-surface border border-[var(--accent)]/30 rounded px-2 py-1 font-theme-data text-xs focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="full">Full</option>
                <option value="summary">Summary</option>
                <option value="minimal">Minimal</option>
              </select>
            </div>
          </div>

          {/* Debate List */}
          <div className="flex items-center justify-between mb-2">
            <button
              onClick={toggleSelectAll}
              className="text-xs font-theme-data text-[var(--acid-cyan)] hover:underline"
            >
              {selectedDebates.size === debates.length ? '[DESELECT ALL]' : '[SELECT ALL]'}
            </button>
            <span className="text-xs font-theme-data text-text-muted">
              {debates.length} debates available
            </span>
          </div>

          {debatesLoading ? (
            <div className="text-center text-text-muted font-theme-data py-8 animate-pulse">
              Loading debates...
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {debates.map((debate) => (
                <label
                  key={debate.id}
                  className={`flex items-center gap-3 p-3 border cursor-pointer transition-colors ${
                    selectedDebates.has(debate.id)
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                      : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedDebates.has(debate.id)}
                    onChange={() => toggleDebateSelection(debate.id)}
                    className="w-4 h-4 accent-acid-green"
                  />
                  <div className="flex-1 min-w-0">
                    <p className="font-theme-data text-sm text-text truncate">{debate.question}</p>
                    <div className="flex gap-3 mt-1">
                      <span className="font-theme-data text-xs text-text-muted">{debate.id}</span>
                      {debate.verdict && (
                        <span
                          className={`font-theme-data text-xs ${
                            debate.verdict === 'pass'
                              ? 'text-green-400'
                              : debate.verdict === 'fail'
                                ? 'text-red-400'
                                : 'text-yellow-400'
                          }`}
                        >
                          {debate.verdict.toUpperCase()}
                        </span>
                      )}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-4 border-t border-[var(--accent)]/20">
            <button
              onClick={startBatchJob}
              disabled={loading || selectedDebates.size === 0}
              className="flex-1 px-4 py-2 font-theme-data text-sm bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
            >
              {loading ? '[STARTING...]' : `[START BATCH] (${selectedDebates.size})`}
            </button>
            <button
              onClick={compareExplanations}
              disabled={loading || selectedDebates.size < 2 || selectedDebates.size > 10}
              className="px-4 py-2 font-theme-data text-sm border border-[var(--acid-cyan)] text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors disabled:opacity-50"
            >
              [COMPARE]
            </button>
          </div>
        </div>
      )}

      {/* Progress Tab */}
      {activeTab === 'progress' && activeBatch && (
        <div className="space-y-6">
          <div className="text-center">
            <div className="text-4xl font-theme-data text-[var(--accent)] mb-2">
              {activeBatch.progress_pct.toFixed(0)}%
            </div>
            <div className="text-sm font-theme-data text-text-muted">
              {activeBatch.processed_count} / {activeBatch.total_debates} debates processed
            </div>
          </div>

          {/* Progress Bar */}
          <div className="h-4 bg-surface rounded overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                activeBatch.status === 'failed'
                  ? 'bg-red-500'
                  : activeBatch.status === 'completed'
                    ? 'bg-[var(--accent)]'
                    : 'bg-[var(--acid-cyan)]'
              }`}
              style={{ width: `${activeBatch.progress_pct}%` }}
            />
          </div>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-4 p-4 bg-bg border border-[var(--accent)]/20">
            <div className="text-center">
              <div className="text-xl font-theme-data text-green-400">
                {activeBatch.success_count}
              </div>
              <div className="text-xs font-theme-data text-text-muted">Success</div>
            </div>
            <div className="text-center">
              <div className="text-xl font-theme-data text-red-400">{activeBatch.error_count}</div>
              <div className="text-xs font-theme-data text-text-muted">Errors</div>
            </div>
            <div className="text-center">
              <div
                className={`text-xl font-theme-data ${
                  activeBatch.status === 'processing'
                    ? 'text-[var(--acid-cyan)] animate-pulse'
                    : activeBatch.status === 'completed'
                      ? 'text-green-400'
                      : activeBatch.status === 'failed'
                        ? 'text-red-400'
                        : 'text-text-muted'
                }`}
              >
                {activeBatch.status.toUpperCase()}
              </div>
              <div className="text-xs font-theme-data text-text-muted">Status</div>
            </div>
          </div>

          {(activeBatch.status === 'completed' || activeBatch.status === 'partial') && (
            <button
              onClick={() => fetchBatchResults(activeBatch.batch_id)}
              className="w-full px-4 py-2 font-theme-data text-sm bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
            >
              [VIEW RESULTS]
            </button>
          )}
        </div>
      )}

      {/* Results Tab */}
      {activeTab === 'results' && batchResults && (
        <div className="space-y-4">
          <div className="text-xs font-theme-data text-text-muted mb-4">
            Showing {batchResults.results.length} of {batchResults.pagination.total} results
          </div>

          <div className="space-y-3 max-h-96 overflow-y-auto">
            {batchResults.results.map((result) => (
              <div
                key={result.debate_id}
                className={`p-4 border ${
                  result.status === 'success' ? 'border-green-500/30' : 'border-red-500/30'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                    {result.debate_id}
                  </span>
                  <span
                    className={`font-theme-data text-xs ${
                      result.status === 'success' ? 'text-green-400' : 'text-red-400'
                    }`}
                  >
                    {result.status.toUpperCase()}
                  </span>
                </div>

                {result.explanation && (
                  <div className="space-y-2">
                    <p className="font-theme-data text-xs text-text-muted line-clamp-2">
                      {result.explanation.narrative}
                    </p>
                    <div className="flex items-center gap-4">
                      <span className="font-theme-data text-xs text-text-muted">
                        Confidence: {(result.explanation.confidence * 100).toFixed(0)}%
                      </span>
                      <span className="font-theme-data text-xs text-text-muted">
                        {result.explanation.factors.length} factors
                      </span>
                      <span className="font-theme-data text-xs text-text-muted">
                        {result.processing_time_ms.toFixed(0)}ms
                      </span>
                    </div>
                  </div>
                )}

                {result.error && (
                  <p className="font-theme-data text-xs text-red-400">{result.error}</p>
                )}
              </div>
            ))}
          </div>

          {batchResults.pagination.has_more && (
            <button className="w-full px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10">
              [LOAD MORE]
            </button>
          )}
        </div>
      )}

      {/* Compare Tab */}
      {activeTab === 'compare' && comparison && (
        <div className="space-y-6">
          {/* Overall Similarity */}
          <div className="text-center p-4 bg-bg border border-[var(--accent)]/20">
            <div className="text-3xl font-theme-data text-[var(--acid-cyan)] mb-1">
              {(comparison.overall_similarity * 100).toFixed(0)}%
            </div>
            <div className="text-xs font-theme-data text-text-muted">Overall Similarity</div>
          </div>

          {/* Common Factors */}
          <div>
            <h4 className="font-theme-data text-sm text-[var(--accent)] mb-3">Common Factors</h4>
            <div className="space-y-2">
              {comparison.common_factors.map((factor, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2 bg-surface border border-[var(--accent)]/20"
                >
                  <span className="font-theme-data text-xs text-text">{factor.name}</span>
                  <div className="flex items-center gap-3">
                    <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                      avg: {(factor.avg_contribution * 100).toFixed(0)}%
                    </span>
                    <span className="font-theme-data text-xs text-text-muted">
                      var: {factor.variance.toFixed(2)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Divergent Factors */}
          {comparison.divergent_factors.length > 0 && (
            <div>
              <h4 className="font-theme-data text-sm text-[var(--acid-yellow)] mb-3">
                Divergent Factors
              </h4>
              <div className="space-y-2">
                {comparison.divergent_factors.map((factor, idx) => (
                  <div key={idx} className="p-2 bg-surface border border-acid-yellow/20">
                    <div className="font-theme-data text-xs text-text mb-2">{factor.name}</div>
                    <div className="grid grid-cols-2 gap-1">
                      {Object.entries(factor.contributions).map(([debateId, contribution]) => (
                        <div key={debateId} className="flex items-center justify-between">
                          <span className="font-theme-data text-[10px] text-text-muted truncate">
                            {debateId}
                          </span>
                          <span
                            className={`font-theme-data text-[10px] ${
                              contribution > 0 ? 'text-green-400' : 'text-red-400'
                            }`}
                          >
                            {(contribution * 100).toFixed(0)}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default BatchExplainabilityPanel;
