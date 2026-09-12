'use client';

import { useState, useEffect, useCallback } from 'react';
import { PanelTemplate } from './shared/PanelTemplate';
import { API_BASE_URL } from '@/config';

interface TierDistribution {
  fast: number;
  medium: number;
  slow: number;
  glacial: number;
}

interface PromotionStats {
  fast_to_medium: number;
  medium_to_slow: number;
  slow_to_glacial: number;
  promotion_rate: number;
}

interface LearningVelocity {
  current: number;
  trend: 'increasing' | 'stable' | 'decreasing';
  percentile_7d: number;
}

interface RetrievalStats {
  avg_latency_ms: number;
  hit_rate: number;
  most_retrieved_topics: string[];
}

interface Recommendation {
  type: string;
  message: string;
  priority: 'low' | 'medium' | 'high';
}

interface MemoryAnalytics {
  summary: { total_memories: number; active_memories: number; tier_distribution: TierDistribution };
  promotions: PromotionStats;
  learning_velocity: LearningVelocity;
  retrieval_stats: RetrievalStats;
  recommendations: Recommendation[];
}

interface MemoryAnalyticsPanelProps {
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

const TIER_COLORS: Record<string, string> = {
  fast: 'bg-cyan-500',
  medium: 'bg-blue-500',
  slow: 'bg-purple-500',
  glacial: 'bg-indigo-500',
};

const PRIORITY_COLORS: Record<string, string> = {
  high: 'text-red-400 bg-red-900/20 border-red-800/30',
  medium: 'text-yellow-400 bg-yellow-900/20 border-yellow-800/30',
  low: 'text-blue-400 bg-blue-900/20 border-blue-800/30',
};

const getTrendIcon = (trend: string): string => {
  if (trend === 'increasing') return '📈';
  if (trend === 'decreasing') return '📉';
  return '➡️';
};

export function MemoryAnalyticsPanel({ apiBase = DEFAULT_API_BASE }: MemoryAnalyticsPanelProps) {
  const [data, setData] = useState<MemoryAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${apiBase}/api/memory/analytics?days=30`);
      if (!res.ok) {
        if (res.status === 503) {
          setData(null);
          return;
        }
        throw new Error(`Failed to fetch memory analytics: ${res.status}`);
      }

      const result = await res.json();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const renderContent = () => {
    if (!data) return null;

    const { summary, promotions, learning_velocity, retrieval_stats, recommendations } = data;
    const totalTier = Object.values(summary.tier_distribution).reduce((a, b) => a + b, 0);

    return (
      <>
        {/* Tier Distribution */}
        <div className="mb-4">
          <div className="text-xs text-text-muted mb-2">TIER DISTRIBUTION</div>
          <div className="h-4 flex rounded overflow-hidden bg-surface mb-2">
            {(['fast', 'medium', 'slow', 'glacial'] as const).map((tier) => {
              const count = summary.tier_distribution[tier] || 0;
              const percent = totalTier > 0 ? (count / totalTier) * 100 : 0;
              return (
                <div
                  key={tier}
                  className={TIER_COLORS[tier]}
                  style={{ width: `${percent}%` }}
                  title={`${tier}: ${count} (${percent.toFixed(1)}%)`}
                />
              );
            })}
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            {(['fast', 'medium', 'slow', 'glacial'] as const).map((tier) => (
              <div key={tier} className="flex items-center gap-1">
                <span className={`w-2 h-2 rounded-sm ${TIER_COLORS[tier]}`} />
                <span className="text-text-muted capitalize">{tier}:</span>
                <span className="text-text">{summary.tier_distribution[tier] || 0}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Key Metrics */}
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="bg-surface rounded p-3">
            <div className="text-lg font-theme-data text-text">
              {(promotions.promotion_rate * 100).toFixed(1)}%
            </div>
            <div className="text-xs text-text-muted">Promotion Rate</div>
          </div>
          <div className="bg-surface rounded p-3">
            <div className="flex items-center gap-1">
              <span className="text-lg font-theme-data text-text">
                {learning_velocity.current.toFixed(1)}
              </span>
              <span>{getTrendIcon(learning_velocity.trend)}</span>
            </div>
            <div className="text-xs text-text-muted">Learning Velocity</div>
          </div>
        </div>

        {/* Retrieval Stats */}
        <div className="mb-4">
          <div className="text-xs text-text-muted mb-2">RETRIEVAL PERFORMANCE</div>
          <div className="flex justify-between items-center bg-surface rounded p-2">
            <div>
              <span className="text-sm font-theme-data text-text">
                {(retrieval_stats.hit_rate * 100).toFixed(0)}%
              </span>
              <span className="text-xs text-text-muted ml-2">hit rate</span>
            </div>
            <div className="text-xs text-text-muted">
              {retrieval_stats.avg_latency_ms.toFixed(1)}ms avg
            </div>
          </div>
          {retrieval_stats.most_retrieved_topics.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {retrieval_stats.most_retrieved_topics.slice(0, 5).map((topic) => (
                <span key={topic} className="text-xs bg-accent/10 text-accent px-2 py-0.5 rounded">
                  {topic}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Recommendations */}
        {recommendations.length > 0 && (
          <div>
            <div className="text-xs text-text-muted mb-2">RECOMMENDATIONS</div>
            <div className="space-y-2">
              {recommendations.slice(0, 3).map((rec, idx) => (
                <div
                  key={idx}
                  className={`p-2 rounded border text-xs ${PRIORITY_COLORS[rec.priority]}`}
                >
                  {rec.message}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Summary Footer */}
        <div className="flex justify-between text-xs text-text-muted pt-3 mt-4 border-t border-border">
          <span>{summary.active_memories.toLocaleString()} active</span>
          <span>30-day analysis</span>
        </div>
      </>
    );
  };

  return (
    <PanelTemplate
      title="MEMORY ANALYTICS"
      icon="🧠"
      loading={loading}
      error={error}
      onRefresh={fetchData}
      badge={data?.summary.total_memories.toLocaleString()}
      isEmpty={!data}
      emptyState={
        <div className="text-text-muted text-sm text-center py-4">
          Memory analytics not available.
        </div>
      }
    >
      {renderContent()}
    </PanelTemplate>
  );
}
