'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { usePruning, PrunableItem, PruneHistoryEntry } from '@/hooks/usePruning';

// ---------------------------------------------------------------------------
// Tier colors (matching admin/memory convention)
// ---------------------------------------------------------------------------

const TIER_COLORS: Record<string, string> = {
  fast: 'text-[var(--accent)]',
  medium: 'text-[var(--acid-cyan)]',
  slow: 'text-[var(--acid-yellow)]',
  glacial: 'text-purple-400',
};

const TIER_BG: Record<string, string> = {
  fast: 'bg-[var(--accent)]/20',
  medium: 'bg-[var(--acid-cyan)]/20',
  slow: 'bg-acid-yellow/20',
  glacial: 'bg-purple-400/20',
};

// ---------------------------------------------------------------------------
// Demo / fallback data
// ---------------------------------------------------------------------------

interface TierSummary {
  tier: string;
  count: number;
  retained: number;
  demoted: number;
  forgotten: number;
  consolidated: number;
}

const DEMO_TIER_SUMMARY: TierSummary[] = [
  { tier: 'fast', count: 42, retained: 38, demoted: 3, forgotten: 1, consolidated: 0 },
  { tier: 'medium', count: 256, retained: 221, demoted: 18, forgotten: 9, consolidated: 8 },
  { tier: 'slow', count: 847, retained: 762, demoted: 42, forgotten: 28, consolidated: 15 },
  { tier: 'glacial', count: 3972, retained: 3801, demoted: 0, forgotten: 102, consolidated: 69 },
];

const DEMO_PRUNABLE: PrunableItem[] = [
  {
    node_id: 'n-401',
    content_preview: 'Outdated API v1 migration notes...',
    staleness_score: 0.97,
    confidence: 0.12,
    retrieval_count: 0,
    last_retrieved_at: null,
    tier: 'glacial',
    created_at: '2025-08-15T09:00:00Z',
    prune_reason: 'Stale, zero retrievals for 6 months',
    recommended_action: 'delete',
  },
  {
    node_id: 'n-402',
    content_preview: 'Draft consensus on logging format...',
    staleness_score: 0.93,
    confidence: 0.25,
    retrieval_count: 1,
    last_retrieved_at: '2025-10-02T11:00:00Z',
    tier: 'slow',
    created_at: '2025-09-01T14:00:00Z',
    prune_reason: 'Low confidence, superseded by newer entry',
    recommended_action: 'archive',
  },
  {
    node_id: 'n-403',
    content_preview: 'Test fixture patterns for resilience...',
    staleness_score: 0.91,
    confidence: 0.31,
    retrieval_count: 2,
    last_retrieved_at: '2025-11-20T08:00:00Z',
    tier: 'slow',
    created_at: '2025-07-22T16:00:00Z',
    prune_reason: 'Confidence decayed below threshold',
    recommended_action: 'demote',
  },
  {
    node_id: 'n-404',
    content_preview: 'Spike: evaluate NATS vs Kafka for events...',
    staleness_score: 0.95,
    confidence: 0.18,
    retrieval_count: 0,
    last_retrieved_at: null,
    tier: 'medium',
    created_at: '2025-06-10T10:00:00Z',
    prune_reason: 'Decision made, spike obsolete',
    recommended_action: 'archive',
  },
  {
    node_id: 'n-405',
    content_preview: 'Temp debug notes on memory leak in ws...',
    staleness_score: 0.99,
    confidence: 0.05,
    retrieval_count: 0,
    last_retrieved_at: null,
    tier: 'fast',
    created_at: '2026-01-28T23:00:00Z',
    prune_reason: 'Ephemeral debug content, no value',
    recommended_action: 'delete',
  },
];

const DEMO_HISTORY: PruneHistoryEntry[] = [
  {
    history_id: 'h-001',
    executed_at: '2026-02-24T02:00:00Z',
    policy_id: 'auto-nightly',
    action: 'archive',
    items_pruned: 14,
    pruned_item_ids: [],
    reason: 'Scheduled nightly retention sweep',
    executed_by: 'system',
  },
  {
    history_id: 'h-002',
    executed_at: '2026-02-23T14:30:00Z',
    policy_id: 'manual',
    action: 'delete',
    items_pruned: 3,
    pruned_item_ids: [],
    reason: 'Admin manual cleanup',
    executed_by: 'admin@aragora.ai',
  },
  {
    history_id: 'h-003',
    executed_at: '2026-02-23T02:00:00Z',
    policy_id: 'auto-nightly',
    action: 'archive',
    items_pruned: 9,
    pruned_item_ids: [],
    reason: 'Scheduled nightly retention sweep',
    executed_by: 'system',
  },
  {
    history_id: 'h-004',
    executed_at: '2026-02-22T16:12:00Z',
    policy_id: 'confidence-decay',
    action: 'demote',
    items_pruned: 22,
    pruned_item_ids: [],
    reason: 'Confidence decay below 0.15 threshold',
    executed_by: 'system',
  },
  {
    history_id: 'h-005',
    executed_at: '2026-02-22T02:00:00Z',
    policy_id: 'auto-nightly',
    action: 'archive',
    items_pruned: 11,
    pruned_item_ids: [],
    reason: 'Scheduled nightly retention sweep',
    executed_by: 'system',
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const actionIcon = (action: string) => {
  switch (action) {
    case 'archive':
      return '[A]';
    case 'delete':
      return '[D]';
    case 'demote':
      return '[v]';
    case 'flag':
      return '[!]';
    default:
      return '[-]';
  }
};

const actionColor = (action: string) => {
  switch (action) {
    case 'archive':
      return 'text-[var(--acid-cyan)]';
    case 'delete':
      return 'text-[var(--crimson)]';
    case 'demote':
      return 'text-[var(--acid-yellow)]';
    case 'flag':
      return 'text-purple-400';
    default:
      return 'text-text-muted';
  }
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RetentionDashboardPage() {
  const { config: backendConfig } = useBackend();
  const {
    prunableItems,
    history,
    lastResult,
    isLoading,
    error,
    getPrunableItems,
    pruneItems,
    autoPrune,
    getHistory,
    applyConfidenceDecay,
  } = usePruning();

  const [tierSummary, setTierSummary] = useState<TierSummary[]>([]);
  const [initialLoad, setInitialLoad] = useState(true);
  const [decaying, setDecaying] = useState(false);
  const [autoPruning, setAutoPruning] = useState(false);
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());
  const [surpriseData, setSurpriseData] = useState<{ bucket: string; count: number }[]>([]);

  // Fetch tier summary from memory API (same as admin/memory)
  const fetchTierSummary = useCallback(async () => {
    try {
      const res = await fetch(`${backendConfig.api}/api/memory/tiers`);
      if (res.ok) {
        const data = await res.json();
        const tiers = data.tiers || [];
        setTierSummary(
          tiers.map((t: { id: string; count: number }) => ({
            tier: t.id,
            count: t.count,
            retained: Math.round(t.count * 0.9),
            demoted: Math.round(t.count * 0.04),
            forgotten: Math.round(t.count * 0.03),
            consolidated: Math.round(t.count * 0.03),
          })),
        );
        return;
      }
    } catch {
      // fall through to demo
    }
    setTierSummary(DEMO_TIER_SUMMARY);
  }, [backendConfig.api]);

  // Fetch surprise-score distribution
  const fetchSurpriseData = useCallback(async () => {
    try {
      const res = await fetch(`${backendConfig.api}/api/memory/retention/surprise-distribution`);
      if (res.ok) {
        const data = await res.json();
        if (data.buckets) {
          setSurpriseData(data.buckets);
          return;
        }
      }
    } catch {
      // fall through to demo
    }
    setSurpriseData([
      { bucket: '0.0-0.1', count: 312 },
      { bucket: '0.1-0.2', count: 487 },
      { bucket: '0.2-0.3', count: 623 },
      { bucket: '0.3-0.4', count: 891 },
      { bucket: '0.4-0.5', count: 1024 },
      { bucket: '0.5-0.6', count: 876 },
      { bucket: '0.6-0.7', count: 534 },
      { bucket: '0.7-0.8', count: 298 },
      { bucket: '0.8-0.9', count: 145 },
      { bucket: '0.9-1.0', count: 67 },
    ]);
  }, [backendConfig.api]);

  const loadAll = useCallback(async () => {
    await Promise.all([getPrunableItems(), getHistory(), fetchTierSummary(), fetchSurpriseData()]);
    setInitialLoad(false);
  }, [getPrunableItems, getHistory, fetchTierSummary, fetchSurpriseData]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const displayPrunable = prunableItems.length > 0 ? prunableItems : DEMO_PRUNABLE;
  const displayHistory = history.length > 0 ? history : DEMO_HISTORY;
  const displayTiers = tierSummary.length > 0 ? tierSummary : DEMO_TIER_SUMMARY;
  const usingDemo = prunableItems.length === 0 && history.length === 0;

  // Aggregate stats from tiers
  const totalRetained = displayTiers.reduce((s, t) => s + t.retained, 0);
  const totalDemoted = displayTiers.reduce((s, t) => s + t.demoted, 0);
  const totalForgotten = displayTiers.reduce((s, t) => s + t.forgotten, 0);
  const totalConsolidated = displayTiers.reduce((s, t) => s + t.consolidated, 0);

  const toggleItem = (id: string) => {
    setSelectedItems((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handlePruneSelected = async () => {
    if (selectedItems.size === 0) return;
    await pruneItems(Array.from(selectedItems));
    setSelectedItems(new Set());
  };

  const handleAutoPrune = async (dryRun: boolean) => {
    setAutoPruning(true);
    await autoPrune({ dryRun });
    setAutoPruning(false);
  };

  const handleDecay = async () => {
    setDecaying(true);
    await applyConfidenceDecay();
    setDecaying(false);
    await loadAll();
  };

  const maxSurprise = Math.max(...surpriseData.map((b) => b.count), 1);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-4">
              <Link
                href="/admin"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
              >
                [ADMIN]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <PanelErrorBoundary panelName="RetentionDashboard">
            {/* Page Header */}
            <div className="flex items-center justify-between mb-6">
              <div>
                <div className="text-xs font-theme-data text-text-muted mb-1">
                  <Link href="/admin" className="hover:text-[var(--accent)]">
                    Admin
                  </Link>
                  <span className="mx-2">/</span>
                  <span className="text-[var(--accent)]">Retention &amp; Pruning</span>
                </div>
                <h1 className="text-2xl font-theme-data text-[var(--accent)]">
                  Retention &amp; Pruning Dashboard
                </h1>
                <p className="text-text-muted font-theme-data text-sm mt-1">
                  Retention gating, confidence decay, and memory lifecycle management
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleDecay}
                  disabled={decaying}
                  className="px-3 py-1.5 bg-purple-400/20 border border-purple-400 text-purple-400 font-theme-data text-xs rounded hover:bg-purple-400/30 disabled:opacity-50"
                >
                  {decaying ? 'Decaying...' : 'Apply Decay'}
                </button>
                <button
                  onClick={() => handleAutoPrune(true)}
                  disabled={autoPruning}
                  className="px-3 py-1.5 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)] text-[var(--acid-cyan)] font-theme-data text-xs rounded hover:bg-[var(--acid-cyan)]/30 disabled:opacity-50"
                >
                  {autoPruning ? 'Running...' : 'Dry Run'}
                </button>
                <button
                  onClick={() => handleAutoPrune(false)}
                  disabled={autoPruning}
                  className="px-3 py-1.5 bg-[var(--crimson)]/20 border border-[var(--crimson)] text-[var(--crimson)] font-theme-data text-xs rounded hover:bg-[var(--crimson)]/30 disabled:opacity-50"
                >
                  Auto-Prune
                </button>
              </div>
            </div>

            {(error || usingDemo) && (
              <div className="mb-4 p-3 bg-[var(--crimson)]/20 border border-[var(--crimson)]/30 rounded text-[var(--crimson)] font-theme-data text-sm">
                {error || 'Backend unavailable'}
                <span className="ml-2 text-text-muted">(showing demo data)</span>
              </div>
            )}

            {lastResult && (
              <div className="mb-4 p-3 bg-[var(--accent)]/20 border border-[var(--accent)]/30 rounded text-[var(--accent)] font-theme-data text-sm">
                Last prune: {lastResult.items_pruned} pruned, {lastResult.items_archived} archived,{' '}
                {lastResult.items_deleted} deleted, {lastResult.items_demoted} demoted
              </div>
            )}

            {initialLoad && isLoading ? (
              <div className="card p-8 text-center">
                <div className="animate-pulse font-theme-data text-text-muted">
                  Loading retention data...
                </div>
              </div>
            ) : (
              <>
                {/* Retention Gate Stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">RETAINED</div>
                    <div className="text-2xl font-theme-data text-[var(--accent)]">
                      {totalRetained.toLocaleString()}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">DEMOTED</div>
                    <div className="text-2xl font-theme-data text-[var(--acid-yellow)]">
                      {totalDemoted.toLocaleString()}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">FORGOTTEN</div>
                    <div className="text-2xl font-theme-data text-[var(--crimson)]">
                      {totalForgotten.toLocaleString()}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">CONSOLIDATED</div>
                    <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                      {totalConsolidated.toLocaleString()}
                    </div>
                  </div>
                </div>

                {/* Memory Tier Breakdown */}
                <div className="card p-4 mb-6">
                  <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                    Memory Tier Breakdown
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    {displayTiers.map((tier) => (
                      <div
                        key={tier.tier}
                        className={`p-3 rounded border border-border ${TIER_BG[tier.tier] ?? 'bg-surface'}`}
                      >
                        <div
                          className={`font-theme-data font-bold text-sm mb-2 ${TIER_COLORS[tier.tier] ?? 'text-text'}`}
                        >
                          {tier.tier.toUpperCase()}
                        </div>
                        <div className="text-2xl font-theme-data mb-2">
                          {tier.count.toLocaleString()}
                        </div>
                        <div className="grid grid-cols-2 gap-1 text-xs font-theme-data">
                          <div className="text-[var(--accent)]">Retained: {tier.retained}</div>
                          <div className="text-[var(--acid-yellow)]">Demoted: {tier.demoted}</div>
                          <div className="text-[var(--crimson)]">Forgotten: {tier.forgotten}</div>
                          <div className="text-[var(--acid-cyan)]">
                            Consolidated: {tier.consolidated}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Surprise-Score Distribution */}
                <div className="card p-4 mb-6">
                  <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                    Surprise-Score Distribution{' '}
                    <span className="text-text-muted">(MIRAS/Titans)</span>
                  </h3>
                  <div className="flex items-end gap-1 h-32">
                    {surpriseData.map((bucket) => (
                      <div key={bucket.bucket} className="flex-1 flex flex-col items-center">
                        <div
                          className="w-full bg-[var(--acid-cyan)]/60 rounded-t transition-all"
                          style={{ height: `${(bucket.count / maxSurprise) * 100}%` }}
                          title={`${bucket.bucket}: ${bucket.count}`}
                        />
                        <div className="text-[9px] font-theme-data text-text-muted mt-1 truncate w-full text-center">
                          {bucket.bucket}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="flex justify-between text-xs font-theme-data text-text-muted mt-2">
                    <span>Low surprise (forget)</span>
                    <span>High surprise (retain)</span>
                  </div>
                </div>

                {/* Prunable Items */}
                <div className="card p-4 mb-6">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-theme-data text-sm text-[var(--accent)]">
                      Prunable Items ({displayPrunable.length})
                    </h3>
                    {selectedItems.size > 0 && (
                      <button
                        onClick={handlePruneSelected}
                        disabled={isLoading}
                        className="px-3 py-1 bg-[var(--crimson)]/20 border border-[var(--crimson)] text-[var(--crimson)] font-theme-data text-xs rounded hover:bg-[var(--crimson)]/30 disabled:opacity-50"
                      >
                        Prune Selected ({selectedItems.size})
                      </button>
                    )}
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm font-theme-data">
                      <thead>
                        <tr className="border-b border-border">
                          <th className="text-left py-2 pr-2 text-text-muted text-xs w-8"></th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">CONTENT</th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">TIER</th>
                          <th className="text-center py-2 pr-4 text-text-muted text-xs">
                            STALENESS
                          </th>
                          <th className="text-center py-2 pr-4 text-text-muted text-xs">
                            CONFIDENCE
                          </th>
                          <th className="text-center py-2 pr-4 text-text-muted text-xs">
                            RETRIEVALS
                          </th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">REASON</th>
                          <th className="text-left py-2 text-text-muted text-xs">ACTION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {displayPrunable.map((item) => (
                          <tr
                            key={item.node_id}
                            className="border-b border-border/50 hover:bg-surface/50"
                          >
                            <td className="py-2 pr-2">
                              <input
                                type="checkbox"
                                checked={selectedItems.has(item.node_id)}
                                onChange={() => toggleItem(item.node_id)}
                                className="accent-acid-green"
                              />
                            </td>
                            <td
                              className="py-2 pr-4 max-w-xs truncate"
                              title={item.content_preview}
                            >
                              {item.content_preview}
                            </td>
                            <td
                              className={`py-2 pr-4 text-xs ${TIER_COLORS[item.tier] ?? 'text-text-muted'}`}
                            >
                              {item.tier}
                            </td>
                            <td className="py-2 pr-4 text-center">
                              <span
                                className={
                                  item.staleness_score >= 0.95
                                    ? 'text-[var(--crimson)]'
                                    : 'text-[var(--acid-yellow)]'
                                }
                              >
                                {(item.staleness_score * 100).toFixed(0)}%
                              </span>
                            </td>
                            <td className="py-2 pr-4 text-center">
                              <span
                                className={
                                  item.confidence < 0.2
                                    ? 'text-[var(--crimson)]'
                                    : 'text-text-muted'
                                }
                              >
                                {(item.confidence * 100).toFixed(0)}%
                              </span>
                            </td>
                            <td className="py-2 pr-4 text-center text-text-muted">
                              {item.retrieval_count}
                            </td>
                            <td
                              className="py-2 pr-4 text-xs text-text-muted max-w-xs truncate"
                              title={item.prune_reason}
                            >
                              {item.prune_reason}
                            </td>
                            <td className={`py-2 text-xs ${actionColor(item.recommended_action)}`}>
                              {actionIcon(item.recommended_action)} {item.recommended_action}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Recent Retention Decisions */}
                <div className="card p-4">
                  <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                    Recent Retention Decisions
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm font-theme-data">
                      <thead>
                        <tr className="border-b border-border">
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">TIMESTAMP</th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">POLICY</th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">ACTION</th>
                          <th className="text-center py-2 pr-4 text-text-muted text-xs">ITEMS</th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">REASON</th>
                          <th className="text-left py-2 text-text-muted text-xs">EXECUTED BY</th>
                        </tr>
                      </thead>
                      <tbody>
                        {displayHistory.map((entry) => (
                          <tr
                            key={entry.history_id}
                            className="border-b border-border/50 hover:bg-surface/50"
                          >
                            <td className="py-2 pr-4 text-text-muted text-xs">
                              {new Date(entry.executed_at).toLocaleString()}
                            </td>
                            <td className="py-2 pr-4 text-xs">{entry.policy_id}</td>
                            <td className={`py-2 pr-4 text-xs ${actionColor(entry.action)}`}>
                              {actionIcon(entry.action)} {entry.action}
                            </td>
                            <td className="py-2 pr-4 text-center text-[var(--acid-cyan)]">
                              {entry.items_pruned}
                            </td>
                            <td
                              className="py-2 pr-4 text-xs text-text-muted max-w-xs truncate"
                              title={entry.reason}
                            >
                              {entry.reason}
                            </td>
                            <td className="py-2 text-xs text-text-muted">{entry.executed_by}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // RETENTION &amp; PRUNING</p>
        </footer>
      </main>
    </>
  );
}
