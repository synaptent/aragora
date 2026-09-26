'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { API_BASE_URL } from '@/config';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { getConfidenceColor, formatRelativeDate } from '../types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UsageStats {
  total_events: number;
  events_by_type: Record<string, number>;
  top_items: Array<{
    item_id: string;
    count: number;
    content?: string;
    node_type?: string;
    confidence?: number;
    last_accessed?: string;
  }>;
  active_users: number;
  period_days: number;
}

interface QualityTrend {
  workspace_id: string;
  days: number;
  snapshots: Array<{
    timestamp: string;
    avg_confidence: number;
    total_items: number;
    verified_count: number;
    contradictions_count: number;
    stale_count: number;
  }>;
}

interface ExtractionStats {
  total_extractions: number;
  total_claims_extracted: number;
  total_promoted: number;
  recent_extractions: Array<{
    debate_id: string;
    topic?: string;
    claims_count: number;
    timestamp: string;
    confidence_avg?: number;
  }>;
}

interface ConfidenceHistoryEntry {
  item_id: string;
  event: string;
  old_confidence: number;
  new_confidence: number;
  reason: string;
  timestamp: string;
}

interface ConfidenceHistory {
  filters: { item_id: string | null; event_type: string | null };
  count: number;
  adjustments: ConfidenceHistoryEntry[];
}

interface AnalyticsStats {
  total_usage_events: number;
  total_quality_snapshots: number;
  knowledge_items: number;
  avg_confidence: number;
  contradictions_detected: number;
  cross_debate_references: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CrossDebateLearningPage() {
  const [usageStats, setUsageStats] = useState<UsageStats | null>(null);
  const [qualityTrend, setQualityTrend] = useState<QualityTrend | null>(null);
  const [extractionStats, setExtractionStats] = useState<ExtractionStats | null>(null);
  const [confidenceHistory, setConfidenceHistory] = useState<ConfidenceHistory | null>(null);
  const [analyticsStats, setAnalyticsStats] = useState<AnalyticsStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // -------------------------------------------------------------------------
  // Data fetching
  // -------------------------------------------------------------------------

  const fetchAllData = useCallback(async () => {
    setLoading(true);
    setError(null);

    const results = await Promise.allSettled([
      fetch(
        `${API_BASE_URL}/api/knowledge/mound/analytics/usage?workspace_id=default&days=30`,
      ).then((r) => (r.ok ? r.json() : null)),
      fetch(
        `${API_BASE_URL}/api/knowledge/mound/analytics/quality/trend?workspace_id=default&days=30`,
      ).then((r) => (r.ok ? r.json() : null)),
      fetch(`${API_BASE_URL}/api/knowledge/mound/extraction/stats`).then((r) =>
        r.ok ? r.json() : null,
      ),
      fetch(`${API_BASE_URL}/api/knowledge/mound/confidence/history?limit=50`).then((r) =>
        r.ok ? r.json() : null,
      ),
      fetch(`${API_BASE_URL}/api/knowledge/mound/analytics/stats`).then((r) =>
        r.ok ? r.json() : null,
      ),
    ]);

    const [usageRes, trendRes, extractRes, confRes, statsRes] = results;

    if (usageRes.status === 'fulfilled' && usageRes.value) {
      setUsageStats(usageRes.value);
    }
    if (trendRes.status === 'fulfilled' && trendRes.value) {
      setQualityTrend(trendRes.value);
    }
    if (extractRes.status === 'fulfilled' && extractRes.value) {
      setExtractionStats(extractRes.value);
    }
    if (confRes.status === 'fulfilled' && confRes.value) {
      setConfidenceHistory(confRes.value);
    }
    if (statsRes.status === 'fulfilled' && statsRes.value) {
      setAnalyticsStats(statsRes.value);
    }

    // If all failed, show error
    const allFailed = results.every(
      (r) => r.status === 'rejected' || (r.status === 'fulfilled' && !r.value),
    );
    if (allFailed) {
      setError('Unable to connect to Knowledge Mound API. Ensure the backend is running.');
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    fetchAllData();
  }, [fetchAllData]);

  // -------------------------------------------------------------------------
  // Render helpers
  // -------------------------------------------------------------------------

  const renderStatsOverview = () => {
    if (!analyticsStats) return null;

    const cards = [
      {
        label: 'Knowledge Items',
        value: analyticsStats.knowledge_items,
        color: 'text-[var(--accent)]',
      },
      {
        label: 'Avg Confidence',
        value: `${Math.round((analyticsStats.avg_confidence ?? 0) * 100)}%`,
        color: getConfidenceColor(analyticsStats.avg_confidence ?? 0),
      },
      {
        label: 'Cross-Debate Refs',
        value: analyticsStats.cross_debate_references ?? 0,
        color: 'text-[var(--acid-cyan)]',
      },
      {
        label: 'Contradictions',
        value: analyticsStats.contradictions_detected ?? 0,
        color: analyticsStats.contradictions_detected > 0 ? 'text-red-400' : 'text-green-400',
      },
      {
        label: 'Usage Events',
        value: analyticsStats.total_usage_events ?? 0,
        color: 'text-blue-400',
      },
      {
        label: 'Quality Snapshots',
        value: analyticsStats.total_quality_snapshots ?? 0,
        color: 'text-purple-400',
      },
    ];

    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
        {cards.map((card) => (
          <div
            key={card.label}
            className="p-4 bg-surface border border-border rounded-lg text-center"
          >
            <div className={`text-2xl font-theme-data ${card.color}`}>{card.value}</div>
            <div className="text-xs text-text-muted mt-1">{card.label}</div>
          </div>
        ))}
      </div>
    );
  };

  const renderCrossDebateFrequency = () => {
    const topItems = usageStats?.top_items;
    if (!topItems || topItems.length === 0) {
      return (
        <div className="p-4 bg-surface border border-border rounded-lg">
          <h3 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
            Cross-Debate Frequency
          </h3>
          <div className="text-center py-8 text-text-muted font-theme-data text-sm">
            No cross-debate usage data yet. Knowledge entries will appear here as they are
            referenced across debates.
          </div>
        </div>
      );
    }

    const maxCount = Math.max(...topItems.map((i) => i.count), 1);

    return (
      <div className="p-4 bg-surface border border-border rounded-lg">
        <h3 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
          Most Referenced Knowledge ({topItems.length})
        </h3>
        <div className="space-y-3 max-h-[400px] overflow-y-auto pr-2">
          {topItems.map((item, idx) => (
            <div key={item.item_id} className="p-3 bg-bg border border-border rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-theme-data text-[var(--accent)]/70">
                    #{idx + 1}
                  </span>
                  <span className="text-xs font-theme-data text-text-muted truncate max-w-[200px]">
                    {item.item_id}
                  </span>
                  {item.node_type && (
                    <span className="px-2 py-0.5 text-xs font-theme-data rounded bg-blue-900/30 text-blue-400">
                      {item.node_type}
                    </span>
                  )}
                </div>
                <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
                  {item.count} refs
                </span>
              </div>
              {item.content && (
                <p className="text-sm text-text line-clamp-2 mb-2">{item.content}</p>
              )}
              <div className="flex items-center justify-between">
                {/* Bar chart indicator */}
                <div className="flex-1 mr-4">
                  <div className="h-1.5 bg-bg rounded-full overflow-hidden border border-border">
                    <div
                      className="h-full bg-[var(--accent)]/60 rounded-full transition-all"
                      style={{ width: `${(item.count / maxCount) * 100}%` }}
                    />
                  </div>
                </div>
                {item.confidence !== undefined && (
                  <span
                    className={`text-xs font-theme-data ${getConfidenceColor(item.confidence)}`}
                  >
                    {Math.round(item.confidence * 100)}%
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderConfidenceTrend = () => {
    const snapshots = qualityTrend?.snapshots;
    if (!snapshots || snapshots.length === 0) {
      return (
        <div className="p-4 bg-surface border border-border rounded-lg">
          <h3 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
            Confidence Trend
          </h3>
          <div className="text-center py-8 text-text-muted font-theme-data text-sm">
            No quality trend data available. Snapshots will appear as the system tracks confidence
            over time.
          </div>
        </div>
      );
    }

    // Build a simple ASCII-style bar chart of avg_confidence over time
    const maxConf = Math.max(...snapshots.map((s) => s.avg_confidence), 0.01);
    const chartHeight = 120;

    return (
      <div className="p-4 bg-surface border border-border rounded-lg">
        <h3 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
          Confidence Trend ({snapshots.length} snapshots)
        </h3>

        {/* Chart */}
        <div className="relative mb-4" style={{ height: chartHeight + 24 }}>
          <div className="flex items-end gap-1 h-full">
            {snapshots.map((snap, idx) => {
              const barHeight = (snap.avg_confidence / maxConf) * chartHeight;
              const barColor =
                snap.avg_confidence >= 0.8
                  ? 'bg-green-400'
                  : snap.avg_confidence >= 0.5
                    ? 'bg-yellow-400'
                    : 'bg-red-400';

              return (
                <div
                  key={idx}
                  className="flex-1 flex flex-col items-center justify-end"
                  style={{ height: chartHeight }}
                >
                  <div className="text-[8px] font-theme-data text-text-muted mb-1">
                    {Math.round(snap.avg_confidence * 100)}%
                  </div>
                  <div
                    className={`w-full min-w-[4px] max-w-[32px] ${barColor} rounded-t opacity-70 hover:opacity-100 transition-opacity`}
                    style={{ height: Math.max(barHeight, 2) }}
                    title={`${new Date(snap.timestamp).toLocaleDateString()} - ${Math.round(snap.avg_confidence * 100)}% avg confidence, ${snap.total_items} items`}
                  />
                  {/* X-axis label for first, last, and middle */}
                  {(idx === 0 ||
                    idx === snapshots.length - 1 ||
                    idx === Math.floor(snapshots.length / 2)) && (
                    <div className="text-[8px] font-theme-data text-text-muted mt-1 whitespace-nowrap">
                      {new Date(snap.timestamp).toLocaleDateString(undefined, {
                        month: 'short',
                        day: 'numeric',
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Summary stats from latest snapshot */}
        {snapshots.length > 0 &&
          (() => {
            const latest = snapshots[snapshots.length - 1];
            return (
              <div className="grid grid-cols-4 gap-3 pt-3 border-t border-border">
                <div className="text-center">
                  <div className="text-sm font-theme-data text-text">{latest.total_items}</div>
                  <div className="text-[10px] text-text-muted">Total Items</div>
                </div>
                <div className="text-center">
                  <div className="text-sm font-theme-data text-green-400">
                    {latest.verified_count}
                  </div>
                  <div className="text-[10px] text-text-muted">Verified</div>
                </div>
                <div className="text-center">
                  <div className="text-sm font-theme-data text-red-400">
                    {latest.contradictions_count}
                  </div>
                  <div className="text-[10px] text-text-muted">Contradictions</div>
                </div>
                <div className="text-center">
                  <div className="text-sm font-theme-data text-yellow-400">
                    {latest.stale_count}
                  </div>
                  <div className="text-[10px] text-text-muted">Stale</div>
                </div>
              </div>
            );
          })()}
      </div>
    );
  };

  const renderRecentExtractions = () => {
    const recent = extractionStats?.recent_extractions;

    return (
      <div className="p-4 bg-surface border border-border rounded-lg">
        <h3 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
          Recent Knowledge Extractions
        </h3>

        {/* Extraction overview */}
        {extractionStats && (
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div className="p-2 bg-bg rounded text-center">
              <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
                {extractionStats.total_extractions}
              </div>
              <div className="text-[10px] text-text-muted">Extractions</div>
            </div>
            <div className="p-2 bg-bg rounded text-center">
              <div className="text-lg font-theme-data text-purple-400">
                {extractionStats.total_claims_extracted}
              </div>
              <div className="text-[10px] text-text-muted">Claims Found</div>
            </div>
            <div className="p-2 bg-bg rounded text-center">
              <div className="text-lg font-theme-data text-green-400">
                {extractionStats.total_promoted}
              </div>
              <div className="text-[10px] text-text-muted">Promoted</div>
            </div>
          </div>
        )}

        {!recent || recent.length === 0 ? (
          <div className="text-center py-6 text-text-muted font-theme-data text-sm">
            No extractions yet. Run a debate to extract knowledge automatically.
          </div>
        ) : (
          <div className="space-y-2 max-h-[300px] overflow-y-auto pr-2">
            {recent.map((ext, idx) => (
              <div
                key={`${ext.debate_id}-${idx}`}
                className="p-3 bg-bg border border-border rounded-lg"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)] truncate max-w-[200px]">
                    {ext.debate_id}
                  </span>
                  <span className="text-xs text-text-muted">
                    {formatRelativeDate(ext.timestamp)}
                  </span>
                </div>
                {ext.topic && <p className="text-sm text-text line-clamp-1 mb-1">{ext.topic}</p>}
                <div className="flex items-center gap-3 text-xs text-text-muted">
                  <span>{ext.claims_count} claims</span>
                  {ext.confidence_avg !== undefined && (
                    <span className={getConfidenceColor(ext.confidence_avg)}>
                      {Math.round(ext.confidence_avg * 100)}% avg
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderConfidenceHistory = () => {
    const adjustments = confidenceHistory?.adjustments;
    if (!adjustments || adjustments.length === 0) {
      return (
        <div className="p-4 bg-surface border border-border rounded-lg">
          <h3 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
            Confidence Adjustments
          </h3>
          <div className="text-center py-6 text-text-muted font-theme-data text-sm">
            No confidence adjustments recorded yet.
          </div>
        </div>
      );
    }

    return (
      <div className="p-4 bg-surface border border-border rounded-lg">
        <h3 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
          Confidence Adjustments ({confidenceHistory?.count ?? 0})
        </h3>
        <div className="space-y-2 max-h-[300px] overflow-y-auto pr-2">
          {adjustments.map((adj, idx) => {
            const delta = adj.new_confidence - adj.old_confidence;
            const isPositive = delta > 0;

            return (
              <div
                key={`${adj.item_id}-${idx}`}
                className="p-3 bg-bg border border-border rounded-lg"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-theme-data text-text-muted truncate max-w-[180px]">
                    {adj.item_id}
                  </span>
                  <span
                    className={`text-xs font-theme-data px-2 py-0.5 rounded ${
                      adj.event === 'validated'
                        ? 'bg-green-900/30 text-green-400'
                        : adj.event === 'contradicted' || adj.event === 'invalidated'
                          ? 'bg-red-900/30 text-red-400'
                          : 'bg-blue-900/30 text-blue-400'
                    }`}
                  >
                    {adj.event}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className={getConfidenceColor(adj.old_confidence)}>
                    {Math.round(adj.old_confidence * 100)}%
                  </span>
                  <span className="text-text-muted">&rarr;</span>
                  <span className={getConfidenceColor(adj.new_confidence)}>
                    {Math.round(adj.new_confidence * 100)}%
                  </span>
                  <span
                    className={`font-theme-data ${isPositive ? 'text-green-400' : 'text-red-400'}`}
                  >
                    ({isPositive ? '+' : ''}
                    {Math.round(delta * 100)}%)
                  </span>
                </div>
                {adj.reason && (
                  <p className="text-[10px] text-text-muted mt-1 line-clamp-1">{adj.reason}</p>
                )}
                <div className="text-[10px] text-text-muted mt-1">
                  {formatRelativeDate(adj.timestamp)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  // -------------------------------------------------------------------------
  // Main render
  // -------------------------------------------------------------------------

  return (
    <main className="min-h-screen bg-bg p-6">
      <PanelErrorBoundary panelName="Cross-Debate Learning">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <div className="mb-8">
            <div className="flex items-center gap-2 mb-2">
              <Link
                href="/knowledge"
                className="text-sm font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                Knowledge Mound
              </Link>
              <span className="text-text-muted">/</span>
              <span className="text-sm font-theme-data text-[var(--accent)]">
                Cross-Debate Learning
              </span>
            </div>
            <h1 className="text-3xl font-theme-data font-bold text-text mb-2">
              Cross-Debate Learning
            </h1>
            <p className="text-text-muted">
              Track how knowledge evolves across debates -- frequency, confidence trends,
              extractions, and contradictions
            </p>
          </div>

          {/* Refresh button */}
          <div className="flex justify-end mb-4">
            <button
              onClick={fetchAllData}
              disabled={loading}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm rounded-lg hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'Refresh Data'}
            </button>
          </div>

          {/* Error state */}
          {error && (
            <div className="mb-6 p-4 bg-red-900/20 border border-red-500/30 rounded-lg">
              <p className="text-sm text-red-400 font-theme-data">{error}</p>
              <p className="text-xs text-text-muted mt-1">
                The dashboard will populate once the Knowledge Mound API is available.
              </p>
            </div>
          )}

          {/* Loading state */}
          {loading && (
            <div className="text-center py-16">
              <div className="text-[var(--accent)] font-theme-data text-lg mb-2">
                Loading dashboard data...
              </div>
              <div className="text-text-muted text-sm">Fetching from Knowledge Mound APIs</div>
            </div>
          )}

          {/* Content */}
          {!loading && (
            <>
              {/* Stats overview */}
              {renderStatsOverview()}

              {/* Main grid */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Left column */}
                <div className="space-y-6">
                  {renderCrossDebateFrequency()}
                  {renderRecentExtractions()}
                </div>

                {/* Right column */}
                <div className="space-y-6">
                  {renderConfidenceTrend()}
                  {renderConfidenceHistory()}
                </div>
              </div>
            </>
          )}
        </div>
      </PanelErrorBoundary>
    </main>
  );
}
