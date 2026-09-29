'use client';

import { useMemo } from 'react';

export interface AgeDistribution {
  bucket: string; // e.g., "< 1 day", "1-7 days", "1-4 weeks", "> 1 month"
  count: number;
  percentage: number;
}

export interface KnowledgeAgeHistogramProps {
  distribution: AgeDistribution[];
  totalDocs: number;
  staleThresholdDays?: number;
  loading?: boolean;
  className?: string;
}

const BUCKET_COLORS: Record<string, string> = {
  '< 1 day': 'bg-[var(--accent)]',
  '1-7 days': 'bg-cyan-400',
  '1-4 weeks': 'bg-yellow-400',
  '> 1 month': 'bg-red-400',
  fresh: 'bg-[var(--accent)]',
  recent: 'bg-cyan-400',
  aging: 'bg-yellow-400',
  stale: 'bg-red-400',
};

function getBucketColor(bucket: string): string {
  const normalizedBucket = bucket.toLowerCase();
  for (const [key, color] of Object.entries(BUCKET_COLORS)) {
    if (normalizedBucket.includes(key.toLowerCase())) {
      return color;
    }
  }
  return 'bg-surface-alt';
}

/**
 * Histogram showing knowledge age distribution.
 */
export function KnowledgeAgeHistogram({
  distribution,
  totalDocs,
  staleThresholdDays = 30,
  loading = false,
  className = '',
}: KnowledgeAgeHistogramProps) {
  const maxPercentage = useMemo(() => {
    return Math.max(...distribution.map((d) => d.percentage), 1);
  }, [distribution]);

  const stalePercentage = useMemo(() => {
    const staleBuckets = distribution.filter(
      (d) =>
        d.bucket.toLowerCase().includes('month') ||
        d.bucket.toLowerCase().includes('stale') ||
        d.bucket.toLowerCase().includes('week'),
    );
    return staleBuckets.reduce((sum, d) => sum + d.percentage, 0);
  }, [distribution]);

  const healthScore = useMemo(() => {
    // Higher is better: fresh docs are good, stale docs are bad
    const freshBuckets = distribution.filter(
      (d) =>
        d.bucket.toLowerCase().includes('day') ||
        d.bucket.toLowerCase().includes('fresh') ||
        d.bucket.toLowerCase().includes('recent'),
    );
    const freshPercentage = freshBuckets.reduce((sum, d) => sum + d.percentage, 0);
    return Math.round(freshPercentage);
  }, [distribution]);

  if (loading) {
    return (
      <div className={`card p-4 ${className}`}>
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-surface rounded w-1/3" />
          <div className="h-32 bg-surface rounded" />
        </div>
      </div>
    );
  }

  return (
    <div className={`card p-4 ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-theme-data font-bold text-sm flex items-center gap-2">
          <span>📊</span> Knowledge Age
        </h3>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Health:</span>
          <span
            className={`text-sm font-theme-data font-bold ${
              healthScore >= 70
                ? 'text-[var(--accent)]'
                : healthScore >= 40
                  ? 'text-yellow-400'
                  : 'text-red-400'
            }`}
          >
            {healthScore}%
          </span>
        </div>
      </div>

      {/* Histogram bars */}
      <div className="space-y-3 mb-4">
        {distribution.map((item) => (
          <div key={item.bucket}>
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-text-muted">{item.bucket}</span>
              <span className="font-theme-data">
                {item.count.toLocaleString()} ({item.percentage.toFixed(1)}%)
              </span>
            </div>
            <div className="h-4 bg-surface rounded overflow-hidden">
              <div
                className={`h-full ${getBucketColor(item.bucket)} transition-all duration-500`}
                style={{ width: `${(item.percentage / maxPercentage) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-3 pt-3 border-t border-border">
        <div className="text-center">
          <div className="text-xl font-theme-data font-bold text-text">
            {totalDocs.toLocaleString()}
          </div>
          <div className="text-xs text-text-muted">Total Docs</div>
        </div>
        <div className="text-center">
          <div
            className={`text-xl font-theme-data font-bold ${
              stalePercentage > 30 ? 'text-red-400' : 'text-[var(--accent)]'
            }`}
          >
            {stalePercentage.toFixed(1)}%
          </div>
          <div className="text-xs text-text-muted">&gt;{staleThresholdDays}d old</div>
        </div>
      </div>

      {/* Stale warning */}
      {stalePercentage > 30 && (
        <div className="mt-3 p-2 bg-red-400/10 border border-red-400/30 rounded text-xs text-red-400">
          ⚠ {stalePercentage.toFixed(0)}% of knowledge is older than {staleThresholdDays} days.
          Consider refreshing connectors.
        </div>
      )}
    </div>
  );
}

export default KnowledgeAgeHistogram;
