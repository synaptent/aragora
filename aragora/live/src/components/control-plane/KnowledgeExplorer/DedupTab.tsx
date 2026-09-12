'use client';

import { useState, useEffect } from 'react';
import { useDedup } from '@/hooks/useDedup';

export interface DedupTabProps {
  workspaceId?: string;
  onMergeComplete?: () => void;
}

/**
 * Deduplication tab for finding and merging duplicate knowledge items.
 */
export function DedupTab({ workspaceId = 'default', onMergeComplete }: DedupTabProps) {
  const {
    clusters,
    report,
    isLoading,
    error,
    findDuplicates,
    generateReport,
    mergeCluster,
    autoMerge,
  } = useDedup({ workspaceId });

  const [similarityThreshold, setSimilarityThreshold] = useState(0.9);
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null);
  const [showReport, setShowReport] = useState(false);
  const [mergeConfirm, setMergeConfirm] = useState<string | null>(null);

  // Load clusters on mount
  useEffect(() => {
    findDuplicates(similarityThreshold);
  }, [findDuplicates, similarityThreshold]);

  const handleScan = async () => {
    await findDuplicates(similarityThreshold);
  };

  const handleGenerateReport = async () => {
    await generateReport(similarityThreshold);
    setShowReport(true);
  };

  const handleMerge = async (clusterId: string) => {
    const result = await mergeCluster(clusterId);
    if (result?.success) {
      setMergeConfirm(null);
      onMergeComplete?.();
    }
  };

  const handleAutoMerge = async (dryRun: boolean) => {
    const result = await autoMerge(dryRun);
    if (result && !dryRun && result.merges_performed > 0) {
      onMergeComplete?.();
    }
  };

  const getRecommendationBadge = (action: string) => {
    switch (action) {
      case 'merge':
        return (
          <span className="px-2 py-0.5 text-xs rounded bg-success/20 text-success">Merge</span>
        );
      case 'review':
        return (
          <span className="px-2 py-0.5 text-xs rounded bg-acid-yellow/20 text-[var(--acid-yellow)]">
            Review
          </span>
        );
      case 'keep_separate':
        return (
          <span className="px-2 py-0.5 text-xs rounded bg-text-muted/20 text-text-muted">Keep</span>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-text-muted">Similarity:</span>
            <input
              type="range"
              min="0.7"
              max="1.0"
              step="0.05"
              value={similarityThreshold}
              onChange={(e) => setSimilarityThreshold(parseFloat(e.target.value))}
              className="w-24"
            />
            <span className="font-theme-data text-[var(--acid-cyan)]">
              {(similarityThreshold * 100).toFixed(0)}%
            </span>
          </label>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleScan}
            disabled={isLoading}
            className="px-3 py-1.5 text-sm border border-[var(--acid-cyan)] text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 rounded disabled:opacity-50"
          >
            {isLoading ? 'Scanning...' : 'Scan'}
          </button>
          <button
            onClick={handleGenerateReport}
            disabled={isLoading}
            className="px-3 py-1.5 text-sm border border-text-muted text-text-muted hover:bg-text-muted/10 rounded disabled:opacity-50"
          >
            Report
          </button>
          <button
            onClick={() => handleAutoMerge(true)}
            disabled={isLoading}
            className="px-3 py-1.5 text-sm border border-acid-yellow text-[var(--acid-yellow)] hover:bg-acid-yellow/10 rounded disabled:opacity-50"
          >
            Preview Auto-Merge
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="p-3 bg-[var(--crimson)]/10 border border-[var(--crimson)] rounded text-sm text-[var(--crimson)]">
          {error}
        </div>
      )}

      {/* Report Modal */}
      {showReport && report && (
        <div className="p-4 border border-panel-border rounded bg-panel-bg">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Deduplication Report</h3>
            <button
              onClick={() => setShowReport(false)}
              className="text-text-muted hover:text-text-primary"
            >
              ✕
            </button>
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-text-muted">Nodes Analyzed:</span>
              <span className="ml-2 font-theme-data">{report.total_nodes_analyzed}</span>
            </div>
            <div>
              <span className="text-text-muted">Clusters Found:</span>
              <span className="ml-2 font-theme-data text-[var(--acid-yellow)]">
                {report.duplicate_clusters_found}
              </span>
            </div>
            <div>
              <span className="text-text-muted">Est. Reduction:</span>
              <span className="ml-2 font-theme-data text-success">
                {report.estimated_reduction_percent.toFixed(1)}%
              </span>
            </div>
            <div>
              <span className="text-text-muted">Generated:</span>
              <span className="ml-2 font-theme-data">
                {new Date(report.generated_at).toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Clusters List */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="text-text-muted">
            {clusters.length} duplicate cluster{clusters.length !== 1 ? 's' : ''} found
          </span>
        </div>

        {clusters.length === 0 && !isLoading && (
          <div className="p-8 text-center text-text-muted">
            No duplicate clusters found at {(similarityThreshold * 100).toFixed(0)}% similarity
            threshold.
          </div>
        )}

        {clusters.map((cluster) => (
          <div
            key={cluster.cluster_id}
            className={`p-3 border rounded ${
              selectedCluster === cluster.cluster_id
                ? 'border-[var(--acid-cyan)] bg-[var(--acid-cyan)]/5'
                : 'border-panel-border hover:border-text-muted'
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <button
                  onClick={() =>
                    setSelectedCluster(
                      selectedCluster === cluster.cluster_id ? null : cluster.cluster_id,
                    )
                  }
                  className="text-text-muted hover:text-text-primary"
                >
                  {selectedCluster === cluster.cluster_id ? '▼' : '▶'}
                </button>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-theme-data text-sm">{cluster.cluster_id}</span>
                    {getRecommendationBadge(cluster.recommended_action)}
                  </div>
                  <div className="text-xs text-text-muted">
                    {cluster.duplicate_count} duplicates ·{' '}
                    {(cluster.avg_similarity * 100).toFixed(0)}% avg similarity
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {mergeConfirm === cluster.cluster_id ? (
                  <>
                    <button
                      onClick={() => handleMerge(cluster.cluster_id)}
                      disabled={isLoading}
                      className="px-2 py-1 text-xs bg-success text-black rounded disabled:opacity-50"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setMergeConfirm(null)}
                      className="px-2 py-1 text-xs border border-text-muted rounded"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => setMergeConfirm(cluster.cluster_id)}
                    className="px-2 py-1 text-xs border border-success text-success hover:bg-success/10 rounded"
                  >
                    Merge
                  </button>
                )}
              </div>
            </div>

            {/* Expanded duplicates */}
            {selectedCluster === cluster.cluster_id && (
              <div className="mt-3 pl-8 space-y-2">
                <div className="text-xs text-text-muted mb-2">
                  Primary:{' '}
                  <span className="font-theme-data text-[var(--acid-cyan)]">
                    {cluster.primary_node_id}
                  </span>
                </div>
                {cluster.duplicates.map((dup) => (
                  <div
                    key={dup.node_id}
                    className="p-2 bg-panel-bg border border-panel-border rounded text-xs"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-theme-data">{dup.node_id}</span>
                      <span className="text-[var(--acid-yellow)]">
                        {(dup.similarity * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="text-text-muted truncate">{dup.content_preview}</div>
                    <div className="flex items-center gap-2 mt-1 text-text-muted">
                      <span>Tier: {dup.tier}</span>
                      <span>·</span>
                      <span>Confidence: {(dup.confidence * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
