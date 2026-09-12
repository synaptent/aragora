'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useDedup, DuplicateCluster, DedupReport } from '@/hooks/useDedup';

// ---------------------------------------------------------------------------
// Demo / fallback data
// ---------------------------------------------------------------------------

const DEMO_REPORT: DedupReport = {
  workspace_id: 'default',
  generated_at: new Date().toISOString(),
  total_nodes_analyzed: 12_847,
  duplicate_clusters_found: 38,
  estimated_reduction_percent: 6.4,
  cluster_count: 38,
};

const DEMO_CLUSTERS: DuplicateCluster[] = [
  {
    cluster_id: 'clst-001',
    primary_node_id: 'node-a1',
    duplicate_count: 3,
    avg_similarity: 1.0,
    recommended_action: 'merge',
    duplicates: [
      {
        node_id: 'node-a2',
        similarity: 1.0,
        content_preview: 'Rate limiter design for API gateway...',
        tier: 'slow',
        confidence: 0.99,
      },
      {
        node_id: 'node-a3',
        similarity: 1.0,
        content_preview: 'Rate limiter design for API gateway...',
        tier: 'glacial',
        confidence: 0.95,
      },
      {
        node_id: 'node-a4',
        similarity: 1.0,
        content_preview: 'Rate limiter design for API gateway...',
        tier: 'medium',
        confidence: 0.92,
      },
    ],
  },
  {
    cluster_id: 'clst-002',
    primary_node_id: 'node-b1',
    duplicate_count: 2,
    avg_similarity: 0.94,
    recommended_action: 'review',
    duplicates: [
      {
        node_id: 'node-b2',
        similarity: 0.94,
        content_preview: 'Authentication flow using OIDC with refresh tokens...',
        tier: 'slow',
        confidence: 0.88,
      },
      {
        node_id: 'node-b3',
        similarity: 0.91,
        content_preview: 'Auth flow for SSO using OIDC refresh grant...',
        tier: 'medium',
        confidence: 0.85,
      },
    ],
  },
  {
    cluster_id: 'clst-003',
    primary_node_id: 'node-c1',
    duplicate_count: 2,
    avg_similarity: 0.97,
    recommended_action: 'merge',
    duplicates: [
      {
        node_id: 'node-c2',
        similarity: 0.97,
        content_preview: 'CircuitBreaker half-open retry strategy...',
        tier: 'glacial',
        confidence: 0.96,
      },
      {
        node_id: 'node-c3',
        similarity: 0.95,
        content_preview: 'Circuit breaker retry in half-open state...',
        tier: 'slow',
        confidence: 0.9,
      },
    ],
  },
  {
    cluster_id: 'clst-004',
    primary_node_id: 'node-d1',
    duplicate_count: 4,
    avg_similarity: 1.0,
    recommended_action: 'merge',
    duplicates: [
      {
        node_id: 'node-d2',
        similarity: 1.0,
        content_preview: 'Kafka consumer offset commit strategy...',
        tier: 'fast',
        confidence: 0.97,
      },
      {
        node_id: 'node-d3',
        similarity: 1.0,
        content_preview: 'Kafka consumer offset commit strategy...',
        tier: 'medium',
        confidence: 0.94,
      },
      {
        node_id: 'node-d4',
        similarity: 1.0,
        content_preview: 'Kafka consumer offset commit strategy...',
        tier: 'slow',
        confidence: 0.91,
      },
      {
        node_id: 'node-d5',
        similarity: 1.0,
        content_preview: 'Kafka consumer offset commit strategy...',
        tier: 'glacial',
        confidence: 0.87,
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const matchTypeLabel = (sim: number) => {
  if (sim >= 1.0) return 'SHA-256 Exact';
  if (sim >= 0.95) return 'Near-Duplicate';
  return 'Jaccard Fuzzy';
};

const matchTypeColor = (sim: number) => {
  if (sim >= 1.0) return 'text-[var(--crimson)]';
  if (sim >= 0.95) return 'text-[var(--acid-yellow)]';
  return 'text-[var(--acid-cyan)]';
};

const actionColor = (action: string) => {
  switch (action) {
    case 'merge':
      return 'text-[var(--accent)]';
    case 'review':
      return 'text-[var(--acid-yellow)]';
    case 'keep_separate':
      return 'text-text-muted';
    default:
      return 'text-text-muted';
  }
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DedupExplorerPage() {
  const {
    clusters,
    report,
    isLoading,
    error,
    findDuplicates,
    generateReport,
    mergeCluster,
    autoMerge,
  } = useDedup();

  const [localReport, setLocalReport] = useState<DedupReport | null>(null);
  const [localClusters, setLocalClusters] = useState<DuplicateCluster[]>([]);
  const [threshold, setThreshold] = useState(0.9);
  const [initialLoad, setInitialLoad] = useState(true);
  const [merging, setMerging] = useState<string | null>(null);
  const [autoMergeRunning, setAutoMergeRunning] = useState(false);
  const [autoMergeResult, setAutoMergeResult] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    const [rpt, cls] = await Promise.all([generateReport(threshold), findDuplicates(threshold)]);
    if (rpt) setLocalReport(rpt);
    if (cls.length > 0) setLocalClusters(cls);
    setInitialLoad(false);
  }, [generateReport, findDuplicates, threshold]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Prefer live data, fall back to demo
  const displayReport = report ?? localReport ?? DEMO_REPORT;
  const displayClusters =
    clusters.length > 0 ? clusters : localClusters.length > 0 ? localClusters : DEMO_CLUSTERS;

  const exactCount = displayClusters.filter((c) => c.avg_similarity >= 1.0).length;
  const nearCount = displayClusters.filter((c) => c.avg_similarity < 1.0).length;
  const totalDupes = displayClusters.reduce((sum, c) => sum + c.duplicate_count, 0);

  const handleMerge = async (clusterId: string, primaryNodeId: string) => {
    setMerging(clusterId);
    await mergeCluster(clusterId, primaryNodeId);
    setMerging(null);
  };

  const handleAutoMerge = async (dryRun: boolean) => {
    setAutoMergeRunning(true);
    setAutoMergeResult(null);
    const result = await autoMerge(dryRun);
    if (result) {
      setAutoMergeResult(
        dryRun
          ? `Dry run: ${result.duplicates_found} duplicates found, ${result.merges_performed} would merge`
          : `Merged ${result.merges_performed} of ${result.duplicates_found} duplicates`,
      );
    }
    setAutoMergeRunning(false);
  };

  const usingDemo = !report && localClusters.length === 0;

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
          <PanelErrorBoundary panelName="DedupExplorer">
            {/* Page Header */}
            <div className="flex items-center justify-between mb-6">
              <div>
                <div className="text-xs font-theme-data text-text-muted mb-1">
                  <Link href="/admin" className="hover:text-[var(--accent)]">
                    Admin
                  </Link>
                  <span className="mx-2">/</span>
                  <span className="text-[var(--accent)]">Deduplication Explorer</span>
                </div>
                <h1 className="text-2xl font-theme-data text-[var(--accent)]">
                  Deduplication Explorer
                </h1>
                <p className="text-text-muted font-theme-data text-sm mt-1">
                  Cross-system duplicate detection: SHA-256 exact match and Jaccard near-duplicate
                  analysis
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleAutoMerge(true)}
                  disabled={autoMergeRunning}
                  className="px-3 py-1.5 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)] text-[var(--acid-cyan)] font-theme-data text-xs rounded hover:bg-[var(--acid-cyan)]/30 disabled:opacity-50"
                >
                  {autoMergeRunning ? 'Running...' : 'Dry Run Auto-Merge'}
                </button>
                <button
                  onClick={() => handleAutoMerge(false)}
                  disabled={autoMergeRunning}
                  className="px-3 py-1.5 bg-[var(--crimson)]/20 border border-[var(--crimson)] text-[var(--crimson)] font-theme-data text-xs rounded hover:bg-[var(--crimson)]/30 disabled:opacity-50"
                >
                  Execute Auto-Merge
                </button>
                <button
                  onClick={loadData}
                  disabled={isLoading}
                  className="px-3 py-1.5 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-xs rounded hover:bg-[var(--accent)]/30 disabled:opacity-50"
                >
                  {isLoading ? 'Scanning...' : 'Rescan'}
                </button>
              </div>
            </div>

            {/* Error / demo notice */}
            {(error || usingDemo) && (
              <div className="mb-4 p-3 bg-[var(--crimson)]/20 border border-[var(--crimson)]/30 rounded text-[var(--crimson)] font-theme-data text-sm">
                {error || 'Backend unavailable'}
                <span className="ml-2 text-text-muted">(showing demo data)</span>
              </div>
            )}

            {autoMergeResult && (
              <div className="mb-4 p-3 bg-[var(--accent)]/20 border border-[var(--accent)]/30 rounded text-[var(--accent)] font-theme-data text-sm">
                {autoMergeResult}
              </div>
            )}

            {initialLoad && isLoading ? (
              <div className="card p-8 text-center">
                <div className="animate-pulse font-theme-data text-text-muted">
                  Scanning for duplicates...
                </div>
              </div>
            ) : (
              <>
                {/* Stats Overview */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      ENTRIES SCANNED
                    </div>
                    <div className="text-2xl font-theme-data text-[var(--accent)]">
                      {displayReport.total_nodes_analyzed.toLocaleString()}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      EXACT DUPLICATES
                    </div>
                    <div className="text-2xl font-theme-data text-[var(--crimson)]">
                      {exactCount}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">SHA-256 match</div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      NEAR-DUPLICATES
                    </div>
                    <div className="text-2xl font-theme-data text-[var(--acid-yellow)]">
                      {nearCount}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">
                      Jaccard similarity
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      TOTAL DUPLICATE NODES
                    </div>
                    <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                      {totalDupes}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      SPACE SAVINGS
                    </div>
                    <div className="text-2xl font-theme-data text-purple-400">
                      {displayReport.estimated_reduction_percent.toFixed(1)}%
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">estimated</div>
                  </div>
                </div>

                {/* Configuration */}
                <div className="card p-4 mb-6">
                  <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                    Configuration
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                      <label className="block text-xs font-theme-data text-text-muted mb-1">
                        Jaccard Similarity Threshold
                      </label>
                      <div className="flex items-center gap-2">
                        <input
                          type="range"
                          min={0.5}
                          max={1.0}
                          step={0.05}
                          value={threshold}
                          onChange={(e) => setThreshold(parseFloat(e.target.value))}
                          className="flex-1 accent-acid-green"
                        />
                        <span className="font-theme-data text-sm text-[var(--accent)] w-12 text-right">
                          {threshold.toFixed(2)}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-end">
                      <div>
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          Exact Match Algorithm
                        </div>
                        <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                          SHA-256 Content Hash
                        </div>
                      </div>
                    </div>
                    <div className="flex items-end">
                      <div>
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          Near-Dup Algorithm
                        </div>
                        <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                          Jaccard Shingling
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Duplicate Clusters Table */}
                <div className="card p-4">
                  <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                    Duplicate Clusters ({displayClusters.length})
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm font-theme-data">
                      <thead>
                        <tr className="border-b border-border">
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">CLUSTER</th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">
                            CONTENT PREVIEW
                          </th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">
                            MATCH TYPE
                          </th>
                          <th className="text-center py-2 pr-4 text-text-muted text-xs">
                            SIMILARITY
                          </th>
                          <th className="text-center py-2 pr-4 text-text-muted text-xs">DUPES</th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">TIERS</th>
                          <th className="text-left py-2 pr-4 text-text-muted text-xs">ACTION</th>
                          <th className="text-right py-2 text-text-muted text-xs"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {displayClusters.map((cluster) => {
                          const tiers = [...new Set(cluster.duplicates.map((d) => d.tier))];
                          const preview = cluster.duplicates[0]?.content_preview ?? '---';
                          return (
                            <tr
                              key={cluster.cluster_id}
                              className="border-b border-border/50 hover:bg-surface/50"
                            >
                              <td className="py-2 pr-4 text-text-muted text-xs">
                                {cluster.cluster_id}
                              </td>
                              <td className="py-2 pr-4 max-w-xs truncate" title={preview}>
                                {preview}
                              </td>
                              <td
                                className={`py-2 pr-4 text-xs ${matchTypeColor(cluster.avg_similarity)}`}
                              >
                                {matchTypeLabel(cluster.avg_similarity)}
                              </td>
                              <td className="py-2 pr-4 text-center">
                                {(cluster.avg_similarity * 100).toFixed(0)}%
                              </td>
                              <td className="py-2 pr-4 text-center text-[var(--acid-cyan)]">
                                {cluster.duplicate_count}
                              </td>
                              <td className="py-2 pr-4 text-xs">
                                {tiers.map((t) => (
                                  <span
                                    key={t}
                                    className="inline-block mr-1 px-1.5 py-0.5 rounded bg-surface text-text-muted"
                                  >
                                    {t}
                                  </span>
                                ))}
                              </td>
                              <td
                                className={`py-2 pr-4 text-xs uppercase ${actionColor(cluster.recommended_action)}`}
                              >
                                {cluster.recommended_action.replace('_', ' ')}
                              </td>
                              <td className="py-2 text-right">
                                {cluster.recommended_action === 'merge' && (
                                  <button
                                    onClick={() =>
                                      handleMerge(cluster.cluster_id, cluster.primary_node_id)
                                    }
                                    disabled={merging === cluster.cluster_id}
                                    className="px-2 py-1 bg-[var(--accent)]/20 border border-[var(--accent)]/50 text-[var(--accent)] text-xs rounded hover:bg-[var(--accent)]/30 disabled:opacity-50"
                                  >
                                    {merging === cluster.cluster_id ? '...' : 'Merge'}
                                  </button>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                        {displayClusters.length === 0 && (
                          <tr>
                            <td colSpan={8} className="py-8 text-center text-text-muted">
                              No duplicate clusters found at threshold {threshold.toFixed(2)}
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Report metadata */}
                <div className="mt-4 text-xs font-theme-data text-text-muted text-right">
                  Report generated:{' '}
                  {displayReport.generated_at
                    ? new Date(displayReport.generated_at).toLocaleString()
                    : 'N/A'}
                  {' | '}Workspace: {displayReport.workspace_id}
                </div>
              </>
            )}
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // DEDUPLICATION EXPLORER</p>
        </footer>
      </main>
    </>
  );
}
