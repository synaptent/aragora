'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import {
  useMemorySources,
  useRetentionDecisions,
  useDedupClusters,
  useUnifiedMemoryQuery,
} from '@/hooks/useUnifiedMemory';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SOURCE_LABELS: Record<string, { label: string; color: string; description: string }> = {
  continuum: {
    label: 'Continuum Memory',
    color: 'text-acid-green',
    description: 'Multi-tier memory (fast/medium/slow/glacial) with TTL-based retention.',
  },
  km: {
    label: 'Knowledge Mound',
    color: 'text-blue-400',
    description: 'Persistent knowledge with 41 adapters, semantic search, and RBAC governance.',
  },
  supermemory: {
    label: 'Supermemory',
    color: 'text-purple-400',
    description: 'Cross-session external memory with surprise-driven retention.',
  },
  claude_mem: {
    label: 'claude-mem',
    color: 'text-yellow-400',
    description: 'MCP-connected claude-mem for external memory bridging.',
  },
};

function getStatusIndicator(status: string) {
  switch (status) {
    case 'active':
    case 'connected':
      return { dot: 'bg-acid-green', badge: 'text-acid-green bg-acid-green/20', label: 'ONLINE' };
    case 'degraded':
      return { dot: 'bg-yellow-400', badge: 'text-yellow-400 bg-yellow-500/20', label: 'DEGRADED' };
    case 'unavailable':
    case 'disconnected':
      return { dot: 'bg-red-400', badge: 'text-red-400 bg-red-500/20', label: 'OFFLINE' };
    default:
      return { dot: 'bg-text-muted', badge: 'text-text-muted bg-surface', label: status.toUpperCase() };
  }
}

function getActionColor(action: string) {
  switch (action) {
    case 'retain': return 'text-acid-green bg-acid-green/20';
    case 'demote': return 'text-yellow-400 bg-yellow-500/20';
    case 'forget': return 'text-red-400 bg-red-500/20';
    case 'consolidate': return 'text-blue-400 bg-blue-400/20';
    default: return 'text-text-muted bg-surface';
  }
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return 'never';
  try {
    const d = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    if (diffMs < 60_000) return `${Math.round(diffMs / 1000)}s ago`;
    if (diffMs < 3_600_000) return `${Math.round(diffMs / 60_000)}m ago`;
    if (diffMs < 86_400_000) return `${Math.round(diffMs / 3_600_000)}h ago`;
    return d.toLocaleDateString();
  } catch {
    return ts;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type Tab = 'overview' | 'search' | 'retention' | 'dedup';

export default function MemoryGatewayPage() {
  const { config: _config } = useBackend();
  const [activeTab, setActiveTab] = useState<Tab>('overview');

  // --- Hook data ---
  const { sources, loading: sourcesLoading } = useMemorySources();
  const { decisions, stats: retentionStats, loading: retentionLoading } = useRetentionDecisions();
  const { clusters, totalDuplicates, loading: dedupLoading } = useDedupClusters();
  const { search, results: searchResults, perSystem, loading: searchLoading, error: searchError } = useUnifiedMemoryQuery();

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSystems, setSelectedSystems] = useState<string[]>(['continuum', 'km', 'supermemory', 'claude_mem']);

  const handleSearch = useCallback(() => {
    if (!searchQuery.trim()) return;
    search(searchQuery, selectedSystems.length > 0 ? selectedSystems : undefined);
  }, [searchQuery, selectedSystems, search]);

  const toggleSystem = useCallback((sys: string) => {
    setSelectedSystems(prev =>
      prev.includes(sys) ? prev.filter(s => s !== sys) : [...prev, sys]
    );
  }, []);

  // Aggregate stats
  const totalEntries = sources.reduce((sum, s) => sum + s.entry_count, 0);
  const activeSources = sources.filter(s => s.status === 'active').length;
  const totalRetentionActions = retentionStats.retained + retentionStats.demoted + retentionStats.forgotten + retentionStats.consolidated;

  const tabs: Array<{ key: Tab; label: string }> = [
    { key: 'overview', label: 'Overview' },
    { key: 'search', label: 'Cross-System Search' },
    { key: 'retention', label: 'Retention Gate' },
    { key: 'dedup', label: 'Dedup Engine' },
  ];

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <header className="border-b border-acid-green/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-3">
              <Link href="/memory" className="text-xs font-mono text-text-muted hover:text-acid-green transition-colors">
                [MEMORY]
              </Link>
              <Link href="/supermemory" className="text-xs font-mono text-text-muted hover:text-acid-green transition-colors">
                [SUPERMEMORY]
              </Link>
              <Link href="/system-intelligence" className="text-xs font-mono text-text-muted hover:text-acid-green transition-colors">
                [INTELLIGENCE]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-mono text-acid-green mb-2">
              {'>'} UNIFIED MEMORY GATEWAY
            </h1>
            <p className="text-text-muted font-mono text-sm">
              Fan-out search across ContinuumMemory, Knowledge Mound, Supermemory, and claude-mem.
              Monitor retention decisions, near-duplicate clusters, and per-system health via{' '}
              <code className="text-acid-green">enable_unified_memory</code>.
            </p>
          </div>

          {/* Aggregate stats bar */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
            <div className="p-3 bg-surface border border-border rounded-lg text-center">
              <div className="text-2xl font-mono font-bold text-acid-green">{sources.length}</div>
              <div className="text-xs text-text-muted uppercase">Sources</div>
            </div>
            <div className="p-3 bg-surface border border-border rounded-lg text-center">
              <div className="text-2xl font-mono font-bold text-blue-400">{activeSources}/{sources.length}</div>
              <div className="text-xs text-text-muted uppercase">Active</div>
            </div>
            <div className="p-3 bg-surface border border-border rounded-lg text-center">
              <div className="text-2xl font-mono font-bold text-purple-400">{totalEntries.toLocaleString()}</div>
              <div className="text-xs text-text-muted uppercase">Total Entries</div>
            </div>
            <div className="p-3 bg-surface border border-border rounded-lg text-center">
              <div className="text-2xl font-mono font-bold text-yellow-400">{totalRetentionActions}</div>
              <div className="text-xs text-text-muted uppercase">Retention Actions</div>
            </div>
            <div className="p-3 bg-surface border border-border rounded-lg text-center">
              <div className="text-2xl font-mono font-bold text-red-400">{totalDuplicates}</div>
              <div className="text-xs text-text-muted uppercase">Duplicates</div>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-2 mb-6 flex-wrap">
            {tabs.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-4 py-2 text-sm font-mono rounded border transition-colors ${
                  activeTab === key
                    ? 'bg-acid-green/20 border-acid-green text-acid-green'
                    : 'border-border text-text-muted hover:border-acid-green/50'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* ================================================================ */}
          {/* TAB: OVERVIEW                                                     */}
          {/* ================================================================ */}
          {activeTab === 'overview' && (
            <PanelErrorBoundary panelName="Memory Sources">
              {sourcesLoading ? (
                <div className="text-acid-green font-mono animate-pulse text-center py-12">
                  Scanning memory subsystems...
                </div>
              ) : sources.length === 0 ? (
                <div className="p-8 bg-surface border border-border rounded-lg text-center">
                  <p className="text-text-muted font-mono">
                    No memory sources detected. Enable unified memory via{' '}
                    <code className="text-acid-green">enable_unified_memory</code> in ArenaConfig.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {sources.map((src) => {
                    const meta = SOURCE_LABELS[src.name] ?? {
                      label: src.name,
                      color: 'text-text',
                      description: '',
                    };
                    const indicator = getStatusIndicator(src.status);
                    return (
                      <div key={src.name} className="p-5 bg-surface border border-border rounded-lg">
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-2">
                            <span className={`w-2 h-2 rounded-full ${indicator.dot} inline-block`} />
                            <span className={`font-mono text-sm font-bold ${meta.color}`}>
                              {meta.label}
                            </span>
                          </div>
                          <span className={`px-2 py-0.5 text-xs font-mono rounded ${indicator.badge}`}>
                            {indicator.label}
                          </span>
                        </div>
                        <p className="text-xs text-text-muted mb-4">{meta.description}</p>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <div className="text-xs text-text-muted uppercase">Entries</div>
                            <div className="text-lg font-mono font-bold text-text">
                              {src.entry_count.toLocaleString()}
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-text-muted uppercase">Last Activity</div>
                            <div className="text-sm font-mono text-text">
                              {formatTimestamp(src.last_activity)}
                            </div>
                          </div>
                        </div>
                        {/* Per-source share bar */}
                        {totalEntries > 0 && (
                          <div className="mt-3">
                            <div className="flex items-center justify-between text-xs text-text-muted mb-1">
                              <span>Share of total</span>
                              <span className="font-mono">
                                {((src.entry_count / totalEntries) * 100).toFixed(1)}%
                              </span>
                            </div>
                            <div className="w-full bg-bg rounded-full h-1.5">
                              <div
                                className={`h-1.5 rounded-full ${
                                  src.name === 'continuum' ? 'bg-acid-green' :
                                  src.name === 'km' ? 'bg-blue-400' :
                                  src.name === 'supermemory' ? 'bg-purple-400' :
                                  'bg-yellow-400'
                                }`}
                                style={{ width: `${Math.max(2, (src.entry_count / totalEntries) * 100)}%` }}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Retention stats summary */}
              {!retentionLoading && totalRetentionActions > 0 && (
                <div className="mt-6 p-4 bg-surface border border-border rounded-lg">
                  <h3 className="text-sm font-mono font-bold text-text-muted uppercase mb-3">
                    Retention Gate Summary
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="p-3 bg-bg rounded-lg text-center">
                      <div className="text-xl font-mono font-bold text-acid-green">{retentionStats.retained}</div>
                      <div className="text-xs text-text-muted uppercase">Retained</div>
                    </div>
                    <div className="p-3 bg-bg rounded-lg text-center">
                      <div className="text-xl font-mono font-bold text-yellow-400">{retentionStats.demoted}</div>
                      <div className="text-xs text-text-muted uppercase">Demoted</div>
                    </div>
                    <div className="p-3 bg-bg rounded-lg text-center">
                      <div className="text-xl font-mono font-bold text-red-400">{retentionStats.forgotten}</div>
                      <div className="text-xs text-text-muted uppercase">Forgotten</div>
                    </div>
                    <div className="p-3 bg-bg rounded-lg text-center">
                      <div className="text-xl font-mono font-bold text-blue-400">{retentionStats.consolidated}</div>
                      <div className="text-xs text-text-muted uppercase">Consolidated</div>
                    </div>
                  </div>
                </div>
              )}

              {/* Dedup stats summary */}
              {!dedupLoading && (totalDuplicates > 0 || clusters.length > 0) && (
                <div className="mt-4 p-4 bg-surface border border-border rounded-lg">
                  <h3 className="text-sm font-mono font-bold text-text-muted uppercase mb-3">
                    Deduplication Summary
                  </h3>
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 bg-bg rounded-lg text-center">
                      <div className="text-xl font-mono font-bold text-red-400">{totalDuplicates}</div>
                      <div className="text-xs text-text-muted uppercase">Total Duplicates</div>
                    </div>
                    <div className="p-3 bg-bg rounded-lg text-center">
                      <div className="text-xl font-mono font-bold text-yellow-400">{clusters.length}</div>
                      <div className="text-xs text-text-muted uppercase">Clusters</div>
                    </div>
                    <div className="p-3 bg-bg rounded-lg text-center">
                      <div className="text-xl font-mono font-bold text-acid-green">
                        {totalDuplicates > 0 ? (totalDuplicates / Math.max(1, clusters.length)).toFixed(1) : '0'}
                      </div>
                      <div className="text-xs text-text-muted uppercase">Avg/Cluster</div>
                    </div>
                  </div>
                </div>
              )}
            </PanelErrorBoundary>
          )}

          {/* ================================================================ */}
          {/* TAB: SEARCH                                                       */}
          {/* ================================================================ */}
          {activeTab === 'search' && (
            <PanelErrorBoundary panelName="Cross-System Search">
              <div className="space-y-4">
                {/* System filter toggles */}
                <div className="flex gap-2 flex-wrap">
                  <span className="text-xs font-mono text-text-muted py-1">Filter:</span>
                  {Object.entries(SOURCE_LABELS).map(([key, meta]) => (
                    <button
                      key={key}
                      onClick={() => toggleSystem(key)}
                      className={`px-3 py-1 text-xs font-mono rounded border transition-colors ${
                        selectedSystems.includes(key)
                          ? `${meta.color} border-current bg-current/10`
                          : 'text-text-muted border-border opacity-50'
                      }`}
                    >
                      {meta.label}
                    </button>
                  ))}
                </div>

                {/* Search bar */}
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                    placeholder="Search across all memory systems..."
                    className="flex-1 px-4 py-2 bg-surface border border-border rounded font-mono text-sm text-text placeholder-text-muted focus:border-acid-green focus:outline-none"
                  />
                  <button
                    onClick={handleSearch}
                    disabled={searchLoading || !searchQuery.trim()}
                    className="px-4 py-2 bg-acid-green/20 border border-acid-green text-acid-green font-mono text-sm rounded hover:bg-acid-green/30 disabled:opacity-50"
                  >
                    {searchLoading ? 'Searching...' : 'Search'}
                  </button>
                </div>

                {searchError && (
                  <div className="p-3 bg-red-500/10 border border-red-500/30 rounded text-red-400 text-sm font-mono">
                    Search failed: {searchError.message}
                  </div>
                )}

                {/* Per-system result counts */}
                {Object.keys(perSystem).length > 0 && (
                  <div className="flex gap-3 flex-wrap">
                    {Object.entries(perSystem).map(([sys, count]) => {
                      const meta = SOURCE_LABELS[sys];
                      return (
                        <span key={sys} className={`px-2 py-1 text-xs font-mono rounded bg-surface border border-border ${meta?.color ?? 'text-text'}`}>
                          {meta?.label ?? sys}: {count}
                        </span>
                      );
                    })}
                  </div>
                )}

                {/* Results */}
                {searchResults.length > 0 && (
                  <div className="p-4 bg-surface border border-border rounded-lg">
                    <h3 className="text-sm font-mono font-bold text-text-muted uppercase mb-3">
                      {searchResults.length} results
                    </h3>
                    <div className="space-y-2 max-h-[500px] overflow-y-auto">
                      {searchResults.map((result, idx) => {
                        const meta = SOURCE_LABELS[result.source];
                        return (
                          <div key={idx} className="p-3 bg-bg rounded">
                            <div className="flex items-center gap-2 mb-1">
                              <span className={`px-1.5 py-0.5 text-xs font-mono rounded bg-surface ${meta?.color ?? 'text-text'}`}>
                                {meta?.label ?? result.source}
                              </span>
                              <span className="text-xs text-text-muted font-mono">
                                relevance: {(result.relevance * 100).toFixed(0)}%
                              </span>
                            </div>
                            <p className="text-sm text-text line-clamp-3">{result.content}</p>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {!searchLoading && searchResults.length === 0 && searchQuery.trim() && !searchError && (
                  <div className="p-4 bg-surface border border-border rounded-lg text-center">
                    <p className="text-text-muted font-mono text-sm">
                      Enter a query and click Search to query across all memory systems.
                    </p>
                  </div>
                )}
              </div>
            </PanelErrorBoundary>
          )}

          {/* ================================================================ */}
          {/* TAB: RETENTION GATE                                               */}
          {/* ================================================================ */}
          {activeTab === 'retention' && (
            <PanelErrorBoundary panelName="Retention Gate">
              {retentionLoading ? (
                <div className="text-acid-green font-mono animate-pulse text-center py-12">
                  Loading retention decisions...
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Stats */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="p-3 bg-surface border border-border rounded-lg text-center">
                      <div className="text-2xl font-mono font-bold text-acid-green">{retentionStats.retained}</div>
                      <div className="text-xs text-text-muted uppercase">Retained</div>
                    </div>
                    <div className="p-3 bg-surface border border-border rounded-lg text-center">
                      <div className="text-2xl font-mono font-bold text-yellow-400">{retentionStats.demoted}</div>
                      <div className="text-xs text-text-muted uppercase">Demoted</div>
                    </div>
                    <div className="p-3 bg-surface border border-border rounded-lg text-center">
                      <div className="text-2xl font-mono font-bold text-red-400">{retentionStats.forgotten}</div>
                      <div className="text-xs text-text-muted uppercase">Forgotten</div>
                    </div>
                    <div className="p-3 bg-surface border border-border rounded-lg text-center">
                      <div className="text-2xl font-mono font-bold text-blue-400">{retentionStats.consolidated}</div>
                      <div className="text-xs text-text-muted uppercase">Consolidated</div>
                    </div>
                  </div>

                  <p className="text-xs text-text-muted font-mono">
                    Titans/MIRAS-inspired surprise-driven decisions. Memories with high surprise scores are retained;
                    stale or low-value entries are demoted, forgotten, or consolidated.
                  </p>

                  {/* Decision stream */}
                  {decisions.length === 0 ? (
                    <div className="p-8 bg-surface border border-border rounded-lg text-center">
                      <p className="text-text-muted font-mono">No retention decisions recorded yet.</p>
                    </div>
                  ) : (
                    <div className="space-y-2 max-h-[500px] overflow-y-auto">
                      {decisions.map((decision, i) => (
                        <div key={i} className="flex items-center gap-3 p-3 bg-surface border border-border rounded">
                          <span className={`px-2 py-0.5 text-xs font-mono rounded whitespace-nowrap ${getActionColor(decision.action)}`}>
                            {decision.action.toUpperCase()}
                          </span>
                          <span className="text-xs text-text font-mono flex-1 truncate" title={decision.memory_id}>
                            {decision.memory_id.substring(0, 20)}...
                          </span>
                          <span className="text-xs text-text-muted whitespace-nowrap">
                            surprise: {decision.surprise_score.toFixed(2)}
                          </span>
                          <span className="text-xs text-text-muted whitespace-nowrap hidden md:inline">
                            {decision.reason}
                          </span>
                          <span className="text-xs text-text-muted whitespace-nowrap">
                            {formatTimestamp(decision.timestamp)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </PanelErrorBoundary>
          )}

          {/* ================================================================ */}
          {/* TAB: DEDUP ENGINE                                                 */}
          {/* ================================================================ */}
          {activeTab === 'dedup' && (
            <PanelErrorBoundary panelName="Dedup Engine">
              {dedupLoading ? (
                <div className="text-acid-green font-mono animate-pulse text-center py-12">
                  Scanning for duplicates...
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Summary */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 bg-surface border border-border rounded-lg text-center">
                      <div className="text-2xl font-mono font-bold text-red-400">{totalDuplicates}</div>
                      <div className="text-xs text-text-muted uppercase">Total Duplicates</div>
                    </div>
                    <div className="p-3 bg-surface border border-border rounded-lg text-center">
                      <div className="text-2xl font-mono font-bold text-yellow-400">{clusters.length}</div>
                      <div className="text-xs text-text-muted uppercase">Clusters</div>
                    </div>
                    <div className="p-3 bg-surface border border-border rounded-lg text-center">
                      <div className="text-2xl font-mono font-bold text-acid-green">
                        {totalDuplicates > 0
                          ? (totalDuplicates / Math.max(1, clusters.length)).toFixed(1)
                          : '0'}
                      </div>
                      <div className="text-xs text-text-muted uppercase">Avg / Cluster</div>
                    </div>
                  </div>

                  <p className="text-xs text-text-muted font-mono">
                    SHA-256 exact + Jaccard near-duplicate detection across all memory systems.
                    Canonical entries are kept; duplicates are flagged for deduplication.
                  </p>

                  {clusters.length === 0 ? (
                    <div className="p-8 bg-surface border border-border rounded-lg text-center">
                      <p className="text-text-muted font-mono">No duplicate clusters detected. Memory is clean.</p>
                    </div>
                  ) : (
                    <div className="space-y-4 max-h-[600px] overflow-y-auto">
                      {clusters.map((cluster) => (
                        <div key={cluster.cluster_id} className="p-4 bg-surface border border-border rounded-lg">
                          <div className="flex items-center gap-2 mb-3">
                            <span className="text-xs font-mono text-text-muted">
                              Cluster: {cluster.cluster_id.substring(0, 12)}
                            </span>
                            <span className="text-xs text-text-muted">
                              {cluster.entries.length} entries
                            </span>
                          </div>
                          {/* Canonical */}
                          <div className="p-2 bg-acid-green/10 border border-acid-green/30 rounded mb-2">
                            <div className="text-xs text-acid-green font-mono mb-1">CANONICAL</div>
                            <p className="text-sm text-text line-clamp-2">{cluster.canonical}</p>
                          </div>
                          {/* Duplicate entries */}
                          <div className="space-y-1">
                            {cluster.entries.map((entry, idx) => {
                              const meta = SOURCE_LABELS[entry.source];
                              return (
                                <div key={idx} className="text-xs p-2 bg-bg rounded flex items-center gap-2">
                                  <span className={`px-1 py-0.5 rounded font-mono ${meta?.color ?? 'text-text'} bg-surface`}>
                                    {meta?.label ?? entry.source}
                                  </span>
                                  <span className="text-text flex-1 line-clamp-1">{entry.content}</span>
                                  <span className="text-text-muted font-mono whitespace-nowrap">
                                    {(entry.similarity * 100).toFixed(0)}% sim
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </PanelErrorBoundary>
          )}
        </div>

        <footer className="text-center text-xs font-mono py-8 border-t border-acid-green/20 mt-8">
          <div className="text-acid-green/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // UNIFIED MEMORY GATEWAY</p>
        </footer>
      </main>
    </>
  );
}
