'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/lib/api';

interface EloChange {
  agent: string;
  delta: number;
  new_rating: number;
  reason: string;
}

interface KmEntry {
  id: string;
  type: string;
  confidence: number;
}

interface FeedbackSummary {
  pipeline_id: string;
  elo_changes: EloChange[];
  km_entries_stored: number;
  km_entries: KmEntry[];
  regressions: Array<Record<string, unknown>>;
  regression_count: number;
}

interface FeedbackLoopPanelProps {
  pipelineId: string;
  isVisible?: boolean;
}

export function FeedbackLoopPanel({ pipelineId, isVisible = true }: FeedbackLoopPanelProps) {
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  const fetchSummary = useCallback(async () => {
    if (!pipelineId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ data: FeedbackSummary }>(
        `/api/v1/self-improve/feedback-summary?pipeline_id=${encodeURIComponent(pipelineId)}`,
      );
      setSummary(data.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load feedback');
    } finally {
      setLoading(false);
    }
  }, [pipelineId]);

  useEffect(() => {
    if (isVisible && pipelineId) {
      fetchSummary();
    }
  }, [isVisible, pipelineId, fetchSummary]);

  if (!isVisible) return null;

  return (
    <div className="border border-[var(--accent)]/30 rounded-lg bg-surface/80 backdrop-blur-sm mt-4">
      {/* Header */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-[var(--accent)]/5 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-[var(--acid-cyan)] font-theme-data text-xs uppercase tracking-wider">
            {'>'} Post-Execution Learning
          </span>
          {summary && !loading && (
            <span className="text-xs font-theme-data text-text-muted">
              ({summary.km_entries_stored} KM entries, {summary.elo_changes.length} ELO changes)
            </span>
          )}
        </div>
        <span className="text-[var(--accent)]/50 font-theme-data text-sm">
          {collapsed ? '[+]' : '[-]'}
        </span>
      </button>

      {!collapsed && (
        <div className="px-4 pb-4 space-y-4">
          {loading && (
            <div className="text-[var(--accent)]/60 font-theme-data text-xs animate-pulse py-2">
              {'>'} Loading feedback data...
            </div>
          )}

          {error && (
            <div className="text-[var(--crimson)]/80 font-theme-data text-xs py-2">
              {'>'} {error}
            </div>
          )}

          {summary && !loading && (
            <>
              {/* ELO Changes */}
              {summary.elo_changes.length > 0 && (
                <div>
                  <h4 className="text-[var(--accent)] font-theme-data text-xs uppercase tracking-wider mb-2">
                    ELO Rating Changes
                  </h4>
                  <div className="space-y-1">
                    {summary.elo_changes.map((change, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between text-xs font-theme-data px-2 py-1 bg-bg/50 rounded"
                      >
                        <span className="text-text">{change.agent}</span>
                        <span
                          className={
                            change.delta > 0
                              ? 'text-green-400'
                              : change.delta < 0
                                ? 'text-red-400'
                                : 'text-text-muted'
                          }
                        >
                          {change.delta > 0 ? '+' : ''}
                          {change.delta} ({change.new_rating})
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* KM Entries */}
              {summary.km_entries_stored > 0 && (
                <div>
                  <h4 className="text-[var(--accent)] font-theme-data text-xs uppercase tracking-wider mb-2">
                    Knowledge Mound Entries ({summary.km_entries_stored})
                  </h4>
                  <div className="space-y-1">
                    {summary.km_entries.map((entry, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between text-xs font-theme-data px-2 py-1 bg-bg/50 rounded"
                      >
                        <span className="text-text">{entry.type}</span>
                        <span className="text-[var(--acid-cyan)]">
                          {(entry.confidence * 100).toFixed(0)}% confidence
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Regressions */}
              {summary.regression_count > 0 && (
                <div>
                  <h4 className="text-[var(--crimson)] font-theme-data text-xs uppercase tracking-wider mb-2">
                    Regressions Detected ({summary.regression_count})
                  </h4>
                  <div className="space-y-1">
                    {summary.regressions.map((reg, i) => (
                      <div
                        key={i}
                        className="text-xs font-theme-data px-2 py-1 bg-red-500/10 border border-red-500/20 rounded text-red-300"
                      >
                        {String(reg.description || reg.message || JSON.stringify(reg))}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Empty state */}
              {summary.elo_changes.length === 0 &&
                summary.km_entries_stored === 0 &&
                summary.regression_count === 0 && (
                  <div className="text-text-muted font-theme-data text-xs py-2">
                    {'>'} No feedback data yet. Execute the pipeline to see learning outcomes.
                  </div>
                )}

              {/* Refresh */}
              <button
                onClick={fetchSummary}
                className="text-xs font-theme-data text-[var(--accent)]/60 hover:text-[var(--accent)] transition-colors"
              >
                [refresh]
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
