'use client';

import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';
import { useAuth } from '@/context/AuthContext';

interface ModelAlternative {
  provider: string;
  model: string;
  cost_per_1k_input: string;
  cost_per_1k_output: string;
  quality_score: number;
  latency_multiplier: number;
}

interface CachingOpportunity {
  pattern: string;
  estimated_hit_rate: number;
  unique_queries: number;
  repeat_count: number;
  cache_strategy: string;
}

interface BatchingOpportunity {
  operation_type: string;
  current_batch_size: number;
  optimal_batch_size: number;
  requests_per_hour: number;
  latency_impact_ms: number;
}

interface Recommendation {
  id: string;
  type:
    | 'model_downgrade'
    | 'caching'
    | 'batching'
    | 'rate_limiting'
    | 'prompt_optimization'
    | 'provider_switch';
  priority: 'critical' | 'high' | 'medium' | 'low';
  status: 'pending' | 'applied' | 'dismissed';
  current_cost_usd: string;
  projected_cost_usd: string;
  estimated_savings_usd: string;
  savings_percentage: number;
  confidence_score: number;
  title: string;
  description: string;
  rationale: string;
  model_alternative?: ModelAlternative;
  caching_opportunity?: CachingOpportunity;
  batching_opportunity?: BatchingOpportunity;
  quality_impact: string;
  quality_impact_score: number;
  risk_level: string;
  auto_apply_available: boolean;
  created_at: string;
}

interface RecommendationSummary {
  total_recommendations: number;
  pending_count: number;
  applied_count: number;
  dismissed_count: number;
  total_potential_savings_usd: string;
  realized_savings_usd: string;
  by_priority: { critical: number; high: number; medium: number; low: number };
}

interface Props {
  workspaceId?: string;
}

const PRIORITY_COLORS = {
  critical: 'border-red-500 bg-red-500/10',
  high: 'border-orange-500 bg-orange-500/10',
  medium: 'border-yellow-500 bg-yellow-500/10',
  low: 'border-green-500 bg-green-500/10',
};

const TYPE_ICONS = {
  model_downgrade: '🔄',
  caching: '💾',
  batching: '📦',
  rate_limiting: '⏱️',
  prompt_optimization: '✂️',
  provider_switch: '🔀',
};

export function OptimizationRecommendations({ workspaceId = 'default' }: Props) {
  const { isAuthenticated, tokens } = useAuth();
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [summary, setSummary] = useState<RecommendationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'pending' | 'applied' | 'dismissed'>('pending');

  const fetchRecommendations = useCallback(async () => {
    if (!isAuthenticated) {
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      const statusParam = filter !== 'all' ? `&status=${filter}` : '';
      const response = await fetch(
        `/api/costs/recommendations?workspace_id=${workspaceId}${statusParam}`,
        { headers },
      );

      if (response.ok) {
        const data = await response.json();
        setRecommendations(data.recommendations || []);
        setSummary(data.summary || null);
      }
    } catch (error) {
      logger.error('Failed to fetch recommendations:', error);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, tokens?.access_token, workspaceId, filter]);

  useEffect(() => {
    fetchRecommendations();
  }, [fetchRecommendations]);

  const handleApply = async (id: string) => {
    setApplying(id);
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      const response = await fetch(`/api/costs/recommendations/${id}/apply`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: 'current_user' }),
      });

      if (response.ok) {
        await fetchRecommendations();
      }
    } catch (error) {
      logger.error('Failed to apply recommendation:', error);
    } finally {
      setApplying(null);
    }
  };

  const handleDismiss = async (id: string) => {
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      const response = await fetch(`/api/costs/recommendations/${id}/dismiss`, {
        method: 'POST',
        headers,
      });

      if (response.ok) {
        await fetchRecommendations();
      }
    } catch (error) {
      logger.error('Failed to dismiss recommendation:', error);
    }
  };

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-[var(--bg)] rounded w-1/3" />
          <div className="h-32 bg-[var(--bg)] rounded" />
          <div className="h-32 bg-[var(--bg)] rounded" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
          {'>'} OPTIMIZATION RECOMMENDATIONS
        </h3>
        {summary && (
          <div className="text-xs font-theme-data text-green-400">
            Potential savings: ${parseFloat(summary.total_potential_savings_usd).toFixed(2)}
          </div>
        )}
      </div>

      {/* Summary Stats */}
      {summary && (
        <div className="grid grid-cols-4 gap-2 text-center">
          <div className="bg-[var(--bg)] rounded p-2">
            <div className="text-lg font-theme-data text-red-400">
              {summary.by_priority.critical}
            </div>
            <div className="text-xs text-[var(--text-muted)]">Critical</div>
          </div>
          <div className="bg-[var(--bg)] rounded p-2">
            <div className="text-lg font-theme-data text-orange-400">
              {summary.by_priority.high}
            </div>
            <div className="text-xs text-[var(--text-muted)]">High</div>
          </div>
          <div className="bg-[var(--bg)] rounded p-2">
            <div className="text-lg font-theme-data text-yellow-400">
              {summary.by_priority.medium}
            </div>
            <div className="text-xs text-[var(--text-muted)]">Medium</div>
          </div>
          <div className="bg-[var(--bg)] rounded p-2">
            <div className="text-lg font-theme-data text-green-400">{summary.by_priority.low}</div>
            <div className="text-xs text-[var(--text-muted)]">Low</div>
          </div>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex border-b border-[var(--border)]">
        {(['pending', 'applied', 'dismissed', 'all'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-2 text-xs font-theme-data transition-colors ${
              filter === f
                ? 'text-[var(--acid-green)] border-b-2 border-[var(--acid-green)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
            {f === 'pending' && summary ? ` (${summary.pending_count})` : ''}
          </button>
        ))}
      </div>

      {/* Recommendations List */}
      <div className="space-y-3 max-h-96 overflow-y-auto">
        {recommendations.length === 0 ? (
          <div className="text-center py-8 text-[var(--text-muted)]">
            <div className="text-2xl mb-2">✨</div>
            <div className="text-sm">No {filter !== 'all' ? filter : ''} recommendations</div>
          </div>
        ) : (
          recommendations.map((rec) => (
            <div key={rec.id} className={`border rounded p-4 ${PRIORITY_COLORS[rec.priority]}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{TYPE_ICONS[rec.type]}</span>
                    <h4 className="text-sm font-theme-data text-[var(--text)]">{rec.title}</h4>
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        rec.status === 'applied'
                          ? 'bg-green-500/20 text-green-400'
                          : rec.status === 'dismissed'
                            ? 'bg-gray-500/20 text-gray-400'
                            : 'bg-[var(--acid-green)]/20 text-[var(--acid-green)]'
                      }`}
                    >
                      {rec.status}
                    </span>
                  </div>
                  <p className="text-xs text-[var(--text-muted)] mt-1">{rec.description}</p>

                  {/* Model Alternative Details */}
                  {rec.model_alternative && (
                    <div className="mt-2 text-xs bg-[var(--bg)] rounded p-2">
                      <div className="text-[var(--text-muted)]">
                        Switch to:{' '}
                        <span className="text-[var(--text)]">{rec.model_alternative.model}</span> (
                        {rec.model_alternative.provider})
                      </div>
                      <div className="text-[var(--text-muted)]">
                        Quality: {(rec.model_alternative.quality_score * 100).toFixed(0)}%{' | '}
                        Latency: {rec.model_alternative.latency_multiplier}x
                      </div>
                    </div>
                  )}

                  {/* Caching Details */}
                  {rec.caching_opportunity && (
                    <div className="mt-2 text-xs bg-[var(--bg)] rounded p-2">
                      <div className="text-[var(--text-muted)]">
                        Strategy:{' '}
                        <span className="text-[var(--text)]">
                          {rec.caching_opportunity.cache_strategy}
                        </span>
                        {' | '}Est. hit rate:{' '}
                        {(rec.caching_opportunity.estimated_hit_rate * 100).toFixed(0)}%
                      </div>
                    </div>
                  )}

                  <div className="flex items-center gap-4 mt-2">
                    <span className="text-xs text-[var(--text-muted)]">
                      Confidence: {(rec.confidence_score * 100).toFixed(0)}%
                    </span>
                    <span className="text-xs text-[var(--text-muted)]">Risk: {rec.risk_level}</span>
                  </div>
                </div>

                <div className="text-right">
                  <div className="text-lg font-theme-data text-green-400">
                    -${parseFloat(rec.estimated_savings_usd).toFixed(2)}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">
                    {rec.savings_percentage.toFixed(0)}% savings
                  </div>

                  {rec.status === 'pending' && (
                    <div className="flex gap-2 mt-3">
                      <button
                        onClick={() => handleApply(rec.id)}
                        disabled={applying === rec.id}
                        className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-green)] text-[var(--bg)] rounded hover:bg-[var(--acid-green)]/80 disabled:opacity-50 transition-colors"
                      >
                        {applying === rec.id ? 'Applying...' : 'Apply'}
                      </button>
                      <button
                        onClick={() => handleDismiss(rec.id)}
                        className="px-3 py-1 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] rounded hover:border-red-500/30 hover:text-red-400 transition-colors"
                      >
                        Dismiss
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default OptimizationRecommendations;
