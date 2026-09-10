'use client';

import { MetricCard } from '@/components/analytics';

interface KnowledgeDashboardProps {
  stats: {
    coverage: number;
    quality: number;
    total_nodes: number;
    contradictions: number;
    top_queries?: string[];
    recommendations?: string[];
  };
  loading?: boolean;
}

export function KnowledgeDashboard({ stats, loading = false }: KnowledgeDashboardProps) {
  return (
    <div className="space-y-4">
      {/* Metric cards grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Coverage"
          value={loading ? '-' : `${(stats.coverage * 100).toFixed(1)}%`}
          subtitle="knowledge coverage"
          color="green"
          loading={loading}
          icon="%"
        />
        <MetricCard
          title="Quality Score"
          value={loading ? '-' : stats.quality.toFixed(2)}
          subtitle="avg quality"
          color="cyan"
          loading={loading}
          icon="*"
        />
        <MetricCard
          title="Total Nodes"
          value={loading ? '-' : stats.total_nodes.toLocaleString()}
          subtitle="knowledge entries"
          color="yellow"
          loading={loading}
          icon="#"
        />
        <MetricCard
          title="Contradictions"
          value={loading ? '-' : stats.contradictions}
          subtitle="detected conflicts"
          color={stats.contradictions > 0 ? 'red' : 'purple'}
          loading={loading}
          icon="!"
        />
      </div>

      {/* Top Queries */}
      {stats.top_queries && stats.top_queries.length > 0 && (
        <div className="card p-4">
          <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">{'>'} TOP QUERIES</h3>
          <div className="space-y-1">
            {stats.top_queries.map((query, i) => (
              <div
                key={i}
                className="flex items-center gap-2 p-2 border border-[var(--accent)]/10 rounded hover:bg-[var(--accent)]/5 transition-colors"
              >
                <span className="text-[var(--acid-cyan)] font-theme-data text-xs w-6">
                  {i + 1}.
                </span>
                <span className="text-text font-theme-data text-sm truncate">{query}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendations */}
      {stats.recommendations && stats.recommendations.length > 0 && (
        <div className="card p-4">
          <h3 className="font-theme-data text-sm text-[var(--acid-yellow)] mb-3">
            {'>'} RECOMMENDATIONS
          </h3>
          <div className="space-y-2">
            {stats.recommendations.map((rec, i) => (
              <div
                key={i}
                className="flex items-start gap-2 p-2 border border-acid-yellow/10 rounded"
              >
                <span className="text-[var(--acid-yellow)] font-theme-data text-xs mt-0.5">-</span>
                <span className="text-text-muted font-theme-data text-xs">{rec}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default KnowledgeDashboard;
