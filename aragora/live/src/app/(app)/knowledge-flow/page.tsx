'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useKnowledgeFlow, useConfidenceHistory, useAdapterHealth } from '@/hooks/useKnowledgeFlow';

type TabKey = 'flow' | 'confidence' | 'adapters';

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'flow', label: 'Flow Visualization' },
  { key: 'confidence', label: 'Confidence History' },
  { key: 'adapters', label: 'Adapter Health' },
];

function getStatusColor(status: string): string {
  switch (status) {
    case 'healthy':
    case 'active':
      return 'text-[var(--accent)] bg-[var(--accent)]/20';
    case 'degraded':
    case 'stale':
      return 'text-yellow-400 bg-yellow-500/20';
    case 'unhealthy':
    case 'offline':
      return 'text-red-400 bg-red-500/20';
    default:
      return 'text-text-muted bg-surface';
  }
}

function getHealthIndicator(health: string): string {
  switch (health) {
    case 'healthy':
      return '[OK]';
    case 'degraded':
      return '[!!]';
    case 'unhealthy':
      return '[XX]';
    default:
      return '[??]';
  }
}

function getConfidenceColor(value: number): string {
  if (value >= 0.7) return 'text-[var(--accent)]';
  if (value >= 0.4) return 'text-yellow-400';
  return 'text-red-400';
}

function getDeltaDisplay(delta: number): { text: string; color: string } {
  if (delta > 0) return { text: `+${(delta * 100).toFixed(1)}%`, color: 'text-[var(--accent)]' };
  if (delta < 0) return { text: `${(delta * 100).toFixed(1)}%`, color: 'text-red-400' };
  return { text: '0.0%', color: 'text-text-muted' };
}

export default function KnowledgeFlowPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('flow');

  const { flows, stats, loading: flowLoading, error: flowError } = useKnowledgeFlow();
  const { entries, loading: confLoading, error: confError } = useConfidenceHistory();
  const {
    adapters,
    total: adapterTotal,
    active: adapterActive,
    stale: adapterStale,
    loading: adapterLoading,
    error: adapterError,
  } = useAdapterHealth();

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-3">
              <Link
                href="/knowledge"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [KNOWLEDGE]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} KNOWLEDGE FLYWHEEL
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Visualize the Debate &rarr; Knowledge Mound &rarr; Debate learning loop. Track
              confidence changes, adapter health, and knowledge flow across the system.
            </p>
          </div>

          {/* Tabs */}
          <div className="flex gap-2 mb-6">
            {TABS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-4 py-2 text-sm font-theme-data rounded border transition-colors ${
                  activeTab === key
                    ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                    : 'border-border text-text-muted hover:border-[var(--accent)]/50'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Flow Visualization Tab */}
          {activeTab === 'flow' && (
            <PanelErrorBoundary panelName="Knowledge Flow">
              {flowLoading ? (
                <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
                  Loading flow data...
                </div>
              ) : flowError ? (
                <div className="p-8 bg-surface border border-red-500/30 rounded-lg text-center">
                  <p className="text-red-400 font-theme-data text-sm">
                    Failed to load flow data. The knowledge flow endpoint may be unavailable.
                  </p>
                </div>
              ) : flows.length === 0 ? (
                <div className="p-8 bg-surface border border-border rounded-lg text-center">
                  <p className="text-text-muted font-theme-data">
                    No flow data available. Run debates with Knowledge Mound enabled.
                  </p>
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Summary Stats */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="p-4 bg-surface border border-border rounded-lg text-center">
                      <div className="text-3xl font-theme-data font-bold text-[var(--accent)]">
                        {stats.total_flows}
                      </div>
                      <div className="text-xs text-text-muted uppercase font-theme-data">
                        Total Flows
                      </div>
                    </div>
                    <div className="p-4 bg-surface border border-border rounded-lg text-center">
                      <div className="text-3xl font-theme-data font-bold text-blue-400">
                        {stats.debates_enriched}
                      </div>
                      <div className="text-xs text-text-muted uppercase font-theme-data">
                        Debates Enriched
                      </div>
                    </div>
                    <div className="p-4 bg-surface border border-border rounded-lg text-center">
                      <div
                        className={`text-3xl font-theme-data font-bold ${
                          stats.avg_confidence_change >= 0 ? 'text-[var(--accent)]' : 'text-red-400'
                        }`}
                      >
                        {stats.avg_confidence_change >= 0 ? '+' : ''}
                        {(stats.avg_confidence_change * 100).toFixed(1)}%
                      </div>
                      <div className="text-xs text-text-muted uppercase font-theme-data">
                        Avg Confidence Change
                      </div>
                    </div>
                  </div>

                  {/* Flow Graph - Visual representation of knowledge flow links */}
                  <div className="p-4 bg-surface border border-border rounded-lg">
                    <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-4">
                      Knowledge Flow Graph
                    </h3>

                    {/* Flow links as a directed graph */}
                    <div className="space-y-2 max-h-[400px] overflow-y-auto">
                      {flows.map((flow, i) => {
                        const delta = getDeltaDisplay(flow.confidence_delta);
                        return (
                          <div
                            key={i}
                            className="flex items-center gap-3 p-3 bg-bg rounded border border-border/50 hover:border-[var(--accent)]/30 transition-colors"
                          >
                            {/* Source debate */}
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              <span className="text-[var(--accent)] font-theme-data text-xs shrink-0">
                                [DEBATE]
                              </span>
                              <span className="text-text font-theme-data text-xs truncate">
                                {flow.source_debate_id.slice(0, 8)}...
                              </span>
                            </div>

                            {/* Arrow */}
                            <span className="text-[var(--accent)] font-theme-data shrink-0">
                              &rarr;
                            </span>

                            {/* KM node */}
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              <span className="text-blue-400 font-theme-data text-xs shrink-0">
                                [KM]
                              </span>
                              <span className="text-text font-theme-data text-xs truncate">
                                {flow.km_node_id.slice(0, 8)}...
                              </span>
                            </div>

                            {/* Target (if exists) */}
                            {flow.target_debate_id && (
                              <>
                                <span className="text-[var(--accent)] font-theme-data shrink-0">
                                  &rarr;
                                </span>
                                <div className="flex items-center gap-2 min-w-0 flex-1">
                                  <span className="text-purple-400 font-theme-data text-xs shrink-0">
                                    [TARGET]
                                  </span>
                                  <span className="text-text font-theme-data text-xs truncate">
                                    {flow.target_debate_id.slice(0, 8)}...
                                  </span>
                                </div>
                              </>
                            )}

                            {/* Confidence delta */}
                            <span className={`font-theme-data text-xs shrink-0 ${delta.color}`}>
                              {delta.text}
                            </span>
                          </div>
                        );
                      })}
                    </div>

                    {/* Content previews */}
                    {flows.some((f) => f.content_preview) && (
                      <div className="mt-4 border-t border-border/50 pt-4">
                        <h4 className="text-xs font-theme-data text-text-muted uppercase mb-2">
                          Recent Knowledge Snippets
                        </h4>
                        <div className="space-y-1">
                          {flows
                            .filter((f) => f.content_preview)
                            .slice(0, 5)
                            .map((flow, i) => (
                              <div
                                key={i}
                                className="text-xs font-theme-data text-text-muted p-2 bg-bg/50 rounded"
                              >
                                <span className="text-[var(--accent)]/60">&gt; </span>
                                {flow.content_preview}
                              </div>
                            ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </PanelErrorBoundary>
          )}

          {/* Confidence History Tab */}
          {activeTab === 'confidence' && (
            <PanelErrorBoundary panelName="Confidence History">
              {confLoading ? (
                <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
                  Loading confidence data...
                </div>
              ) : confError ? (
                <div className="p-8 bg-surface border border-red-500/30 rounded-lg text-center">
                  <p className="text-red-400 font-theme-data text-sm">
                    Failed to load confidence history.
                  </p>
                </div>
              ) : entries.length === 0 ? (
                <div className="p-8 bg-surface border border-border rounded-lg text-center">
                  <p className="text-text-muted font-theme-data">
                    No confidence history available yet.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {entries.map((entry) => (
                    <div
                      key={entry.node_id}
                      className="p-4 bg-surface border border-border rounded-lg"
                    >
                      <div className="flex items-center justify-between mb-3">
                        <div>
                          <span className="font-theme-data text-sm text-text">
                            {entry.content_preview || entry.node_id}
                          </span>
                          <span className="ml-2 text-xs font-theme-data text-text-muted">
                            ({entry.confidence_history.length} changes)
                          </span>
                        </div>
                        <span className="text-xs font-theme-data text-text-muted">
                          {entry.node_id.slice(0, 12)}...
                        </span>
                      </div>

                      {/* Confidence timeline as mini inline chart */}
                      <div className="flex items-end gap-px h-16 mb-2">
                        {entry.confidence_history.map((point, i) => {
                          const heightPct = Math.max(point.value * 100, 2);
                          return (
                            <div
                              key={i}
                              className="flex-1 min-w-[4px] max-w-[24px] rounded-t transition-all"
                              style={{
                                height: `${heightPct}%`,
                                backgroundColor:
                                  point.value >= 0.7
                                    ? 'var(--acid-green)'
                                    : point.value >= 0.4
                                      ? '#facc15'
                                      : '#f87171',
                                opacity: 0.7 + (i / entry.confidence_history.length) * 0.3,
                              }}
                              title={`${(point.value * 100).toFixed(1)}% - ${point.reason}`}
                            />
                          );
                        })}
                      </div>

                      {/* History entries */}
                      <div className="space-y-1 max-h-[200px] overflow-y-auto">
                        {entry.confidence_history.map((point, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-3 text-xs font-theme-data p-1.5 bg-bg rounded"
                          >
                            <span className="text-text-muted w-32 shrink-0">
                              {new Date(point.timestamp).toLocaleString()}
                            </span>
                            <span className={`shrink-0 ${getConfidenceColor(point.value)}`}>
                              {(point.value * 100).toFixed(1)}%
                            </span>
                            <span className="text-text-muted truncate flex-1">{point.reason}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </PanelErrorBoundary>
          )}

          {/* Adapter Health Tab */}
          {activeTab === 'adapters' && (
            <PanelErrorBoundary panelName="Adapter Health">
              {adapterLoading ? (
                <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
                  Loading adapter health...
                </div>
              ) : adapterError ? (
                <div className="p-8 bg-surface border border-red-500/30 rounded-lg text-center">
                  <p className="text-red-400 font-theme-data text-sm">
                    Failed to load adapter health data.
                  </p>
                </div>
              ) : adapters.length === 0 ? (
                <div className="p-8 bg-surface border border-border rounded-lg text-center">
                  <p className="text-text-muted font-theme-data">
                    No adapter health data available.
                  </p>
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Adapter summary bar */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="p-4 bg-surface border border-border rounded-lg text-center">
                      <div className="text-3xl font-theme-data font-bold text-[var(--accent)]">
                        {adapterTotal}
                      </div>
                      <div className="text-xs text-text-muted uppercase font-theme-data">
                        Total Adapters
                      </div>
                    </div>
                    <div className="p-4 bg-surface border border-border rounded-lg text-center">
                      <div className="text-3xl font-theme-data font-bold text-[var(--accent)]">
                        {adapterActive}
                      </div>
                      <div className="text-xs text-text-muted uppercase font-theme-data">
                        Active
                      </div>
                    </div>
                    <div className="p-4 bg-surface border border-border rounded-lg text-center">
                      <div
                        className={`text-3xl font-theme-data font-bold ${adapterStale > 0 ? 'text-yellow-400' : 'text-[var(--accent)]'}`}
                      >
                        {adapterStale}
                      </div>
                      <div className="text-xs text-text-muted uppercase font-theme-data">Stale</div>
                    </div>
                  </div>

                  {/* Adapter cards grid */}
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {adapters.map((adapter) => (
                      <div
                        key={adapter.name}
                        className="p-4 bg-surface border border-border rounded-lg hover:border-[var(--accent)]/30 transition-colors"
                      >
                        <div className="flex items-center justify-between mb-3">
                          <span className="font-theme-data text-sm text-text font-bold">
                            {adapter.name}
                          </span>
                          <span
                            className={`px-2 py-0.5 text-xs font-theme-data rounded ${getStatusColor(adapter.status)}`}
                          >
                            {adapter.status.toUpperCase()}
                          </span>
                        </div>

                        <div className="grid grid-cols-2 gap-2 text-xs font-theme-data mb-3">
                          <div>
                            <span className="text-text-muted">Entries: </span>
                            <span className="text-text">{adapter.entry_count}</span>
                          </div>
                          <div>
                            <span className="text-text-muted">Health: </span>
                            <span className={getStatusColor(adapter.health).split(' ')[0]}>
                              {getHealthIndicator(adapter.health)}
                            </span>
                          </div>
                        </div>

                        {adapter.last_sync && (
                          <div className="text-xs font-theme-data">
                            <span className="text-text-muted">Last sync: </span>
                            <span className="text-text">
                              {new Date(adapter.last_sync).toLocaleString()}
                            </span>
                          </div>
                        )}
                        {!adapter.last_sync && (
                          <div className="text-xs font-theme-data text-text-muted">
                            Never synced
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </PanelErrorBoundary>
          )}
        </div>

        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // KNOWLEDGE FLYWHEEL</p>
        </footer>
      </main>
    </>
  );
}
