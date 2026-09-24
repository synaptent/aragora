'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/context/AuthContext';
import { logger } from '@/utils/logger';

interface EfficiencyData {
  workspace_id: string;
  time_range: string;
  metrics: {
    cost_per_1k_tokens: number;
    tokens_per_call: number;
    cost_per_call: number;
    total_tokens: number;
    total_calls: number;
    total_cost: number;
  };
  model_utilization: Array<{ model: string; cost: string; percentage: number }>;
}

interface Props {
  workspaceId?: string;
  timeRange?: '24h' | '7d' | '30d' | '90d';
}

export function EfficiencyMetrics({ workspaceId = 'default', timeRange = '7d' }: Props) {
  const { isAuthenticated, tokens } = useAuth();
  const [data, setData] = useState<EfficiencyData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchEfficiency = useCallback(async () => {
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

      const response = await fetch(
        `/api/costs/efficiency?workspace_id=${workspaceId}&range=${timeRange}`,
        { headers },
      );

      if (response.ok) {
        const result = await response.json();
        setData(result);
      }
    } catch (error) {
      logger.error('Failed to fetch efficiency metrics:', error);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, tokens?.access_token, workspaceId, timeRange]);

  useEffect(() => {
    fetchEfficiency();
  }, [fetchEfficiency]);

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-[var(--bg)] rounded w-1/3" />
          <div className="grid grid-cols-3 gap-4">
            <div className="h-20 bg-[var(--bg)] rounded" />
            <div className="h-20 bg-[var(--bg)] rounded" />
            <div className="h-20 bg-[var(--bg)] rounded" />
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
          {'>'} EFFICIENCY METRICS
        </h3>
        <div className="text-center py-8 text-[var(--text-muted)]">
          No efficiency data available
        </div>
      </div>
    );
  }

  const { metrics, model_utilization } = data;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 space-y-4">
      {/* Header */}
      <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} EFFICIENCY METRICS</h3>

      {/* Key Metrics */}
      <div className="grid grid-cols-3 gap-4">
        <MetricCard
          label="Cost per 1K Tokens"
          value={`$${metrics.cost_per_1k_tokens.toFixed(4)}`}
          color="text-[var(--acid-green)]"
          trend={getTrend(metrics.cost_per_1k_tokens, 0.003)}
        />
        <MetricCard
          label="Tokens per Call"
          value={formatNumber(metrics.tokens_per_call)}
          color="text-[var(--acid-cyan)]"
          trend={getTrend(metrics.tokens_per_call, 1500, true)}
        />
        <MetricCard
          label="Cost per Call"
          value={`$${metrics.cost_per_call.toFixed(4)}`}
          color="text-purple-400"
          trend={getTrend(metrics.cost_per_call, 0.01)}
        />
      </div>

      {/* Model Utilization */}
      {model_utilization.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-xs font-theme-data text-[var(--text-muted)]">Model Utilization</h4>
          <div className="space-y-2">
            {model_utilization.slice(0, 5).map((model, idx) => (
              <div key={model.model} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[var(--text)] font-theme-data">{model.model}</span>
                  <span className="text-[var(--text-muted)]">
                    ${parseFloat(model.cost).toFixed(2)} ({model.percentage.toFixed(1)}%)
                  </span>
                </div>
                <div className="h-2 bg-[var(--bg)] rounded-full overflow-hidden">
                  <div
                    className="h-full transition-all duration-500"
                    style={{ width: `${model.percentage}%`, backgroundColor: getModelColor(idx) }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary */}
      <div className="flex items-center justify-between pt-2 border-t border-[var(--border)]">
        <span className="text-xs text-[var(--text-muted)]">
          Total: {formatNumber(metrics.total_tokens)} tokens / {formatNumber(metrics.total_calls)}{' '}
          calls
        </span>
        <span className="text-xs font-theme-data text-[var(--acid-green)]">
          ${metrics.total_cost.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: string;
  color: string;
  trend?: 'up' | 'down' | 'stable';
}

function MetricCard({ label, value, color, trend }: MetricCardProps) {
  const trendIcon = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→';
  const trendColor =
    trend === 'up' ? 'text-red-400' : trend === 'down' ? 'text-green-400' : 'text-gray-400';

  return (
    <div className="bg-[var(--bg)] rounded p-3">
      <div className="flex items-center gap-2">
        <span className={`text-lg font-theme-data ${color}`}>{value}</span>
        {trend && <span className={`text-xs ${trendColor}`}>{trendIcon}</span>}
      </div>
      <div className="text-xs text-[var(--text-muted)] mt-1">{label}</div>
    </div>
  );
}

function getTrend(
  value: number,
  baseline: number,
  higherIsBetter = false,
): 'up' | 'down' | 'stable' {
  const diff = (value - baseline) / baseline;
  if (Math.abs(diff) < 0.1) return 'stable';
  if (diff > 0) return higherIsBetter ? 'down' : 'up';
  return higherIsBetter ? 'up' : 'down';
}

function formatNumber(num: number): string {
  if (num >= 1000000) {
    return `${(num / 1000000).toFixed(1)}M`;
  }
  if (num >= 1000) {
    return `${(num / 1000).toFixed(1)}K`;
  }
  return Math.round(num).toString();
}

function getModelColor(index: number): string {
  const colors = ['#00ff9d', '#00d4ff', '#a855f7', '#f59e0b', '#22c55e'];
  return colors[index % colors.length];
}

export default EfficiencyMetrics;
